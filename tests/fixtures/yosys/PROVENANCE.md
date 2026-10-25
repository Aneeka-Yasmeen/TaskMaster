# Yosys fixtures: provenance

The `*_stat.rpt` files are **real Yosys output**, generated on 2026-10-18 with
`Yosys 0.9 (git sha1 1979e0b)` (Ubuntu 22.04 package, under WSL2) from **synthetic designs written for
TaskMaster** (`demo/yosys/mac_v1.v`, `mac_v2.v`, `mac_v3_hier.v`). No third-party RTL is involved.

| File | Command |
|---|---|
| mac_v1_stat.rpt | `read_verilog mac_v1.v; synth -top mac; tee -o mac_v1_stat.rpt stat` |
| mac_v2_stat.rpt | `read_verilog mac_v2.v; synth -top mac; tee -o mac_v2_stat.rpt stat` |
| mac_v2_xilinx_stat.rpt | `read_verilog mac_v2.v; synth_xilinx -top mac; tee -o mac_v2_xilinx_stat.rpt stat` |
| mac_v3_hier_stat.rpt | `read_verilog mac_v3_hier.v; synth -top mac; tee -o mac_v3_hier_stat.rpt stat -top mac` |

Yosys 0.9 has no `stat -json`; JSON tests use a **synthetic** fixture built inside
`tests/test_yosys.py` in the documented `stat -json` layout. Malformed and newer-layout inputs are
also synthetic and constructed in the tests.
