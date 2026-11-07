from pathlib import Path
import difflib

w = Path(__file__).resolve().parent
s = (w / 'verify-launch.cpp').read_text()
if '#include <future>' not in s:
    s = '#include <future>\n' + s
needle = '''std::atomic<const Verifier*> g_diag_verifier{nullptr};'''
assert s.count(needle) == 1
s = s.replace(needle, needle + '''
// The single active TP window has one submission per device. Avoid querying a stream
// while its submission still holds runtime locks, or before it has actually been queued.
std::atomic<unsigned> g_tp_submission_active[64]{};
bool tp_submission_busy(int device) {
    return device >= 0 && device < 64 && g_tp_submission_active[device].load(std::memory_order_acquire) != 0;
}''')
needle = '''    {   // (the two launches' host time: a graph of ~1,100 nodes costs the runtime per node; ms_launch reports it)
        const Clock::time_point tl = Clock::now();
        const char* launch_threads = std::getenv("STRATA_TP_LAUNCH_THREADS");
        if (launch_threads && launch_threads[0] == '1') {'''
replacement = '''    // Some Windows HIP graph submissions can remain inside the runtime while GPU kernels
    // already wait for CPU work. Serve those requests before joining the submission threads.
    std::future<cudaError_t> pending_launch[2];
    const char* service_env = std::getenv("STRATA_TP_SERVICE_DURING_LAUNCH");
    const bool service_launch = service_env && service_env[0] == '1';
    {   // (the two launches' host time: a graph of ~1,100 nodes costs the runtime per node; ms_launch reports it)
        const Clock::time_point tl = Clock::now();
        const char* launch_threads = std::getenv("STRATA_TP_LAUNCH_THREADS");
        if (service_launch) {
            for (int r = 0; r < 2; ++r) {
                const int device = v[r]->device_;
                if (device >= 0 && device < 64) g_tp_submission_active[device].fetch_add(1, std::memory_order_release);
                pending_launch[r] = std::async(std::launch::async, [&, r, T] {
                    Verifier* x = v[r];
                    const OnDevice on(x->device_);
                    const cudaError_t le = cudaGraphLaunch(x->ex(T), x->cs_);
                    if (x->device_ >= 0 && x->device_ < 64)
                        g_tp_submission_active[x->device_].fetch_sub(1, std::memory_order_release);
                    x->trace_ev("LAUNCHED", -1, -1, (int64_t) le);
                    (void) cudaStreamQuery(x->cs_);
                    return le;
                });
            }
        } else if (launch_threads && launch_threads[0] == '1') {'''
assert s.count(needle) == 1
s = s.replace(needle, replacement)
start = s.index('bool Verifier::serve_rings(')
end = s.index('// ================================ TENSOR PARALLEL', start)
part = s[start:end]
needle = '''            if (now - last_flush > std::chrono::microseconds(2000)) {'''
assert part.count(needle) == 1
part = part.replace(needle, '''            if (!tp_submission_busy(device_) && now - last_flush > std::chrono::microseconds(2000)) {''')
s = s[:start] + part + s[end:]
needle = '''    if (!second->serve_rings(T, pool, user, false, nullptr, nullptr, err)) return false;
    progress_at("verify window: waiting for the GPUs to finish the window", (int64_t) T);'''
replacement = '''    if (!second->serve_rings(T, pool, user, false, nullptr, nullptr, err)) return false;
    for (auto& launch : pending_launch)
        if (launch.valid()) {
            const cudaError_t le = launch.get();
            if (le != cudaSuccess) { err = std::string("verify: launch: ") + cudaGetErrorString(le); return false; }
        }
    progress_at("verify window: waiting for the GPUs to finish the window", (int64_t) T);'''
assert s.count(needle) == 1
s = s.replace(needle, replacement)
(w / 'verify-service.cpp').write_text(s)
(w / 'service-during-launch.patch').write_text(''.join(difflib.unified_diff(
    (w / 'verify.cpp').read_text().splitlines(True), s.splitlines(True),
    fromfile='a/src/core/verify.cpp', tofile='b/src/core/verify.cpp')))
print('VERIFY_SERVICE_SOURCE_READY')
