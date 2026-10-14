# Production runtime diagnostic — completed baseline

Closure status (2026-10-15): production commit `94e6741` has completed runtime
version and Moshier verification, 25/25 Manglik verification and 18/18 production
versus offline synthetic behavior parity. These are the confirmed baseline;
no repeat diagnostic execution is required for local closure. Raw floating-point
longitude equality across platforms is not a behavior-parity requirement.
The execution instructions below are retained as historical procedure, not a
pending approval request. Secure export and backfill have not been executed.

Script: `scripts/diagnose_manglik_runtime.py`. It is standalone except for installed
calculation dependencies and the approved repository's timezone resolver, verified
against a hardcoded SHA-256 before loading. It never imports app, factory,
full_kundali_api, database adapters or application services. Python audit guards
reject network operations, database/application imports, subprocesses and ordinary
filesystem writes. Run it in a fresh process with `-B`; it writes only JSON to stdout.
The guards are defense in depth, not an OS sandbox for malicious native code.

## Local execution

```powershell
.\venv\Scripts\python.exe -B scripts/diagnose_manglik_runtime.py --source-root .
.\venv\Scripts\python.exe -B -m unittest test_manglik_runtime_diagnostic -v
```

Output contains Python version/executable, working directory, package/native
versions, the native extension hash, allowlisted ephemeris environment settings,
immediate known ephemeris-file inventories/hashes, per-body requested/returned
flags, synthetic longitudes and Lahiri ayanamsa, and five timezone/DST checks.
It does not dump environment variables. TZ/Gunicorn/Python override values are
not printed; only their presence is reported. Suspicious path values are redacted.
Use a restricted console/output location because runtime paths are internal metadata.

The diagnostic requests FLG_SIDEREAL | FLG_SWIEPH, calls SIDM_LAHIRI explicitly,
and uses the approved chart's julday -> swe.calc API sequence without correcting
or changing that sequence. Four synthetic years (1900, 1950, 2000, 2050) and five
bodies (Sun, Moon, Mars, Jupiter, mean node) run in each of two scenarios:
fresh process defaults and production's known set_ephe_path('./ephe') emulation.
Both scenarios change only this disposable process's native calculation state.

The binding has no effective ephemeris search-path getter. The report labels that
limitation and reports environment/configured path plus actual returned flags.
File slots can contain attempted paths or retained earlier opens; only a regular
file with valid date coverage and a hash is labeled a verified asset. A mean node
SWIEPH result alone does not establish planetary asset availability. Inventories
are limited to immediate known ephemeris files in cwd/ephe, safe environment path
entries, and verified asset parents. No recursive service/home-directory crawl.
Explicit JPL or custom worker-only configuration requires separate evidence.

`checks_pass=true` means diagnostics ran successfully, sidereal flags were
returned, and expected timezone/DST cases passed. It does not assert SWIEPH use
or production parity. Moshier is explicitly reported, not treated as diagnostic
failure. A missing dependency, changed resolver, unavailable calculation or failed
timezone check returns nonzero status; exception text and tracebacks are suppressed.

## Historical Render execution procedure

Render supports shell/SSH access for eligible services. Account permissions,
service plan, and access to this deployment have not been inspected. Owner access
to the existing service's Shell or SSH is required; no connector/session was
established. Official reference: https://render.com/docs/ssh

1. Owner approves this exact diagnostic artifact/hash and execution on the backend
   web service's active deployment 94e6741, not the cron service or another release.
2. Use existing-instance Shell/SSH where available. Confirm the deployment identity
   through existing dashboard evidence; the script's approved_commit is an expected
   label, not proof of the running deployment. Do not launch app.py or use Flask shell.
3. Use an approved temporary local file transfer/paste of this standalone script
   into the instance (for example /tmp/diagnose_manglik_runtime.py), without git
   changes, deployment, dependency installation or a public API. This future local
   temporary-file staging requires approval; it has not occurred. Verify SHA-256
   against the reviewed local artifact before execution.
4. Start from the deployment's actual application working directory with its existing
   Python interpreter and inherited service environment. Do not source .env or
   print environment dumps. Replace the placeholders below with verified paths.

```sh
sha256sum /tmp/diagnose_manglik_runtime.py
/path/to/service/python -B /tmp/diagnose_manglik_runtime.py --source-root /path/to/deployed/repository
```

5. Keep stdout in an owner-approved restricted evidence location. Avoid shell
   tracing, broad logging and chat uploads of environment/screens. Remove only the
   exact staged temporary script and any temporary evidence files after the owner
   retains the approved report; do not perform broad cleanup.

An ephemeral shell uses the service image but does not run its start command;
therefore it is not evidence of existing worker initialization or later native
state. Even an existing-instance shell launches a fresh diagnostic process and
cannot read Gunicorn workers' in-memory Swiss Ephemeris state. The path emulation
captures the known startup call, not unknown later calls or thread-specific state.
No worker instrumentation or public endpoint is proposed in this phase.

## Historical comparison procedure (completed)

Compare local and owner-approved production reports: installed versions, effective
backend flags, asset inventory/coverage, longitudes and ayanamsa, timezone outcomes,
environment path configuration and working directory. Native extension hashes
normally differ across operating systems; assess package/native versions and
synthetic numeric results rather than requiring Windows/Linux binary hash identity.
Retain worker/startup configuration evidence separately. These probes do not
compute a full Manglik report or inspect real-user records: deployed Manglik
synthetic-output matching remains a separate required gate, along with active
source identity and worker-specific state/configuration verification.

Runtime and synthetic behavior comparison are complete for the confirmed baseline.
Secure snapshot export and production backfill still require their separate owner
approvals and live connection/storage/privilege preflight. No production execution
is authorized by this document.
