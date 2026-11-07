from pathlib import Path
import difflib

w = Path(__file__).resolve().parent
s = (w / 'prefill-main.cpp').read_text()
needle = '''    const int64_t C = std::min({chunk, a.impl_->T, b.impl_->T});   // the current layouts (relayout may be < T_max)'''
replacement = '''    const char* main_env = std::getenv("STRATA_DP_MAIN_ONLY");
    const bool main_only = main_env && main_env[0] == '1';
    // An idle path keeps its previous layout; its chunk capacity does not constrain main-only work.
    const int64_t C = main_only ? std::min(chunk, b.impl_->T) : std::min({chunk, a.impl_->T, b.impl_->T});'''
assert s.count(needle) == 1
s = s.replace(needle, replacement)
needle = '''    const char* main_env = std::getenv("STRATA_DP_MAIN_ONLY");
    const bool main_only = main_env && main_env[0] == '1';
    for (size_t i = 0; i < plan.size(); ++i)'''
assert s.count(needle) == 1
s = s.replace(needle, '''    for (size_t i = 0; i < plan.size(); ++i)''')
needle = '''    const int me = dp_index_;
    const int my_dev = m.device, peer_dev = pm.device;'''
replacement = '''    const int me = dp_index_;
    const char* final_env = std::getenv("STRATA_DP_FINAL_PUBLISH");
    const bool final_only = final_env && final_env[0] == '1' && !dp_plan_.empty() &&
        std::all_of(dp_plan_.begin(), dp_plan_.end(), [me](const DpChunk& c) { return c.who == me; });
    // No peer consumes intermediate states when every chunk stays on this device.
    if (final_only && (size_t) k + 1 < dp_plan_.size()) return true;
    const int my_dev = m.device, peer_dev = pm.device;'''
assert s.count(needle) == 1
s = s.replace(needle, replacement)
needle = '''        const int64_t r0 = std::min<int64_t>(p0 / blk, a.idx_pooled_rows);'''
assert s.count(needle) == 1
s = s.replace(needle, '''        // The final hand-off includes the full index prefix skipped by earlier chunks.
        const int64_t r0 = final_only ? 0 : std::min<int64_t>(p0 / blk, a.idx_pooled_rows);''')
(w / 'prefill-main-keep.cpp').write_text(s)

s = (w / 'generate.cpp').read_text()
needle = '''                bool any = false;
                if (strata::prefill::Prefill::tp_prefill_env()) strata::prefill::Prefill::set_tp_layout(tp_read);
                for (PfPart& p : pf_parts) {
                    if (p.first < 0) continue;'''
replacement = '''                bool any = false;
                const char* keep_env = std::getenv("STRATA_DP_MAIN_KEEP_CACHE");
                const char* main_env = std::getenv("STRATA_DP_MAIN_ONLY");
                // Only skip an idle path's loan when this segment is guaranteed to use main-only DP.
                // Heads, planned checkpoints, TP prefill and shorter requests retain both original layouts.
                const bool keep_idle = keep_env && keep_env[0] == '1' && main_env && main_env[0] == '1' &&
                    o.batch == 0 && pf_plan_chunk <= 0 && resume_plan.chunk <= 0 && sp.plan_chunk(tokens) <= 0 &&
                    exact <= 0 && !tp_read && dp_on && dp_head(a0) == 0 &&
                    dp_takes(tokens, o.prefill_chunk);
                if (strata::prefill::Prefill::tp_prefill_env()) strata::prefill::Prefill::set_tp_layout(tp_read);
                for (PfPart& p : pf_parts) {
                    if (p.first < 0) continue;
                    if (keep_idle && p.sp == &sp) {
                        // Return any earlier segment's loan before keeping this cache resident.
                        if (!p.lent.empty() && !refill_one(p, e)) return false;
                        if (trace) std::fprintf(stderr, "strata trace: main-only DP keeps CUDA0's expert cache resident\\n");
                        continue;
                    }'''
assert s.count(needle) == 1
s = s.replace(needle, replacement)
(w / 'generate-main-keep.cpp').write_text(s)
patch = ''
for original, modified, target in [('prefill.cpp', 'prefill-main-keep.cpp', 'src/prefill/prefill.cpp'),
                                   ('generate.cpp', 'generate-main-keep.cpp', 'src/program/generate.cpp')]:
    patch += ''.join(difflib.unified_diff((w / original).read_text().splitlines(True),
                                        (w / modified).read_text().splitlines(True),
                                        fromfile='a/' + target, tofile='b/' + target))
(w / 'main-keep-cache.patch').write_text(patch)
print('MAIN_KEEP_SOURCE_READY')
