# MI-08 Windows qualification diagnostic

Date: 2026-10-08
Source commit: 8a395f05b786188d87a923585c6daabad8bd8543
Source tree digest: 044944e454eec695b18ab71dea95f34a6e252c5205e513b9d467da87371dc780

The Windows x86_64 CPython 3.13.11 cell passed 26/26 acceptance cases with zero skips. Its receipt is evidence/local/mi08-platform-receipts/windows-py3.13.json (file SHA-256 7ed7d5971860220cf235c433b5993d4fb0932c41cd1ab87fb9bf90823d661947; report digest 4252c867a8fbf0aa143b963298349cf873a072f4b50f7f770a114f4617458a59).

The interpreter's GetModuleFileNameW image path was a UV junction path. A block rule on that reported path was enabled and visible in ActiveStore but did not block the connection. The junction target was the same executable (SHA-256 A633E1606AF17E54308AFC7E9178150045595EE906819BB499A33C7A02B01989). A second block rule on that canonical target returned Windows socket denial 10013. Both rules were active for the acceptance run; the exact image-path rule still matched the verifier's required process identity. The pre-rule connection control succeeded, the runner isolation probe returned VERIFIED, and both temporary rules were removed after verification. The other Windows Python cells blocked egress with one image-path rule.

The M3 full local gate also passed on Windows 3.14: 216/216 cases, zero skips. Its receipt is evidence/local/M3.json (file SHA-256 ae47f7a02c67fd5684f6f90b2931f724c97353baa471ef77289997e50d27d643; report digest 77262f36d1a5d3ee5372fa68d4a4b1c1cefd4b23eda5a6ca3137541abae23997). The first local M3 attempt without an active firewall rule is preserved as evidence/local/archive-20261008/M3-windows-host-unisolated-failure.json.

No default outbound policy or machine-wide firewall setting was changed. The manual Ubuntu M3 workflow qualification remains pending.
