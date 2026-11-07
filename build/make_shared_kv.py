"""Avoid allocating an unused pinned KV copy for full-geometry DP foreign sessions.

Only independent source copies are changed. Original public entry points retain
their ABI; TP head-sliced sessions retain the original allocation path.
"""
import difflib
from pathlib import Path

w = Path(__file__).resolve().parent

def replace_once(s, old, new):
    if s.count(old) != 1:
        raise RuntimeError('Expected one anchor: ' + old[:100])
    return s.replace(old, new, 1)

layer = (w / 'layer.cpp').read_text()
old_signature = '''uint64_t qsa_state_init(const ModelGeometry& g, int64_t max_cells, void* base, QsaState& st,
                        const QsaState* share_rope, int64_t ring_cells) {'''
new_layer = replace_once(layer, old_signature, '''uint64_t qsa_state_init_shared_kv(const ModelGeometry& g, int64_t max_cells, void* base, QsaState& st,
                                  const QsaState* share_rope, int64_t ring_cells, const QsaState* shared_host) {''')
new_layer = replace_once(new_layer, '''    if (p.mode != 0) {
        const uint64_t hrows''', '''    if (shared_host != nullptr) {
        // Only DP foreign sessions with the owner's full geometry may borrow this
        // backing. TP half-head caches have a different layout and never use this.
        if (p.mode != 1 || ring_cells > 0 || shared_host->kv_mode != p.mode ||
            shared_host->n_pages != pages || shared_host->max_cells != max_cells ||
            shared_host->kv_int8 != st.kv_int8 || shared_host->kv_q4 != st.kv_q4 ||
            shared_host->kv_hybrid != st.kv_hybrid || shared_host->kv_rot != st.kv_rot ||
            (st.kv_hybrid && (!shared_host->host.k_q || !shared_host->host.k_scale || !shared_host->host.v_q4)) ||
            (st.kv_q4 && (!shared_host->host.k_q4 || !shared_host->host.v_q4)) ||
            (st.kv_int8 && (!shared_host->host.k_q || !shared_host->host.v_q ||
                            !shared_host->host.k_scale || !shared_host->host.v_scale)) ||
            (!st.kv_hybrid && !st.kv_q4 && !st.kv_int8 &&
             (!shared_host->host.k_pool || !shared_host->host.v_pool))) {
            std::fprintf(stderr, "strata: DP shared host KV: incompatible owner\\n");
            return 0;
        }
        st.host = shared_host->host;
        const uint64_t avoided = (uint64_t) pages * strata::kernels::kv_block_bytes(s, qsa_kv_format(st)) + 4 * 256;
        std::fprintf(stderr, "strata: DP shared host KV: avoided %llu bytes of unused pinned allocation\\n",
                     (unsigned long long) avoided);
    } else if (p.mode != 0) {
        const uint64_t hrows''')
new_layer = replace_once(new_layer, '\nvoid qsa_state_zero(', '''
uint64_t qsa_state_init(const ModelGeometry& g, int64_t max_cells, void* base, QsaState& st,
                        const QsaState* share_rope, int64_t ring_cells) {
    return qsa_state_init_shared_kv(g, max_cells, base, st, share_rope, ring_cells, nullptr);
}

void qsa_state_zero(''')

session = (w / 'session.cpp').read_text()
new_session = replace_once(session, 'namespace strata::core {\nnamespace {', '''namespace strata::core {
uint64_t qsa_state_init_shared_kv(const ModelGeometry&, int64_t, void*, QsaState&,
                                  const QsaState*, int64_t, const QsaState*);
namespace {''')
new_session = replace_once(new_session, '''uint64_t session_init(const ModelGeometry& g, int64_t max_cells, int64_t k, void* base, SessionState& s,
                      int64_t layer_lo, int64_t layer_hi, const QsaState* share_rope) {''', '''uint64_t session_init_shared_kv(const ModelGeometry& g, int64_t max_cells, int64_t k, void* base, SessionState& s,
                                int64_t layer_lo, int64_t layer_hi, const QsaState* share_rope,
                                const SessionState* host_owner) {''')
new_session = replace_once(new_session, '''    for (int64_t j = 0; j < s.qsa_alloc; ++j)
        if (qsa_state_init(g, max_cells, qp + (j == 0 ? 0 : first + (uint64_t) (j - 1) * rest),
                           s.qsa_states[s.qsa_ord0 + j], j == 0 ? share_rope : &s.qsa_states[s.qsa_ord0]) == 0)
            return 0;''', '''    if (host_owner != nullptr &&
        (host_owner->max_cells != max_cells || host_owner->qsa_states == nullptr ||
         host_owner->qsa_ord0 > s.qsa_ord0 ||
         host_owner->qsa_ord0 + host_owner->qsa_alloc < s.qsa_ord0 + s.qsa_alloc)) {
        std::fprintf(stderr, "strata: DP shared host KV: owner session range mismatch\\n");
        return 0;
    }
    for (int64_t j = 0; j < s.qsa_alloc; ++j) {
        const int64_t q = s.qsa_ord0 + j;
        if (qsa_state_init_shared_kv(g, max_cells, qp + (j == 0 ? 0 : first + (uint64_t) (j - 1) * rest),
                                    s.qsa_states[q], j == 0 ? share_rope : &s.qsa_states[s.qsa_ord0],
                                    0, host_owner ? &host_owner->qsa_states[q] : nullptr) == 0)
            return 0;
    }''')
new_session = replace_once(new_session, '\nvoid session_release(', '''
uint64_t session_init(const ModelGeometry& g, int64_t max_cells, int64_t k, void* base, SessionState& s,
                      int64_t layer_lo, int64_t layer_hi, const QsaState* share_rope) {
    return session_init_shared_kv(g, max_cells, k, base, s, layer_lo, layer_hi, share_rope, nullptr);
}

void session_release(''')

generate = (w / 'generate-main-keep.cpp').read_text()
new_generate = replace_once(generate, '#include "strata/core/session.hpp"', '''#include "strata/core/session.hpp"
namespace strata::core {
uint64_t session_init_shared_kv(const ModelGeometry&, int64_t, int64_t, void*, SessionState&,
                                int64_t, int64_t, const QsaState*, const SessionState*);
}''')
new_generate = replace_once(new_generate, '''            if ((!shared && cudaMalloc(&buf, dbytes) != cudaSuccess) ||
                strata::core::session_init(g, o.max_context, K, buf, dp_ss[i], lo, hi, rope) == 0) {''', '''            strata::core::SessionState& owner = i == 0 ? st0.ss : ss;
            if ((!shared && cudaMalloc(&buf, dbytes) != cudaSuccess) ||
                strata::core::session_init_shared_kv(g, o.max_context, K, buf, dp_ss[i], lo, hi, rope, &owner) == 0) {''')
new_generate = replace_once(new_generate, '''            strata::core::SessionState& owner = i == 0 ? st0.ss : ss;
            for (int64_t q = dp_ss[i].qsa_ord0; q < dp_ss[i].qsa_ord0 + dp_ss[i].qsa_alloc; ++q)
                dp_ss[i].qsa_states[q].host = owner.qsa_states[q].host;
''', '')

patch = []
for name, old, new in [('layer', layer, new_layer), ('session', session, new_session), ('generate', generate, new_generate)]:
    (w / (name + '-shared-kv.cpp')).write_text(new, encoding='utf-8')
    patch.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=name + '-original.cpp', tofile=name + '-shared-kv.cpp'))
(w / 'shared-kv.patch').write_text(''.join(patch), encoding='utf-8')
print('SHARED_KV_SOURCES_READY')
