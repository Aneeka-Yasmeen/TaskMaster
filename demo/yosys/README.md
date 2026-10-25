# Yosys demo designs and reports

Synthetic designs written for TaskMaster (no third-party RTL) and **real Yosys 0.9 `stat` output** for them.

| Design | What changed | Report |
|---|---|---|
| `mac_v1.v` | 8-bit multiply-accumulate, single cycle | `mac_v1_stat.rpt` (478 cells, 20 FFs) |
| `mac_v2.v` | product registered first (one pipeline stage) | `mac_v2_stat.rpt` (501 cells, 36 FFs), `mac_v2_xilinx_stat.rpt` (FPGA-mapped) |
| `mac_v3_hier.v` | multiplier as a submodule | `mac_v3_hier_stat.rpt` (design hierarchy summary, 486 cells) |

Regenerate (WSL): `yosys -p 'read_verilog mac_v2.v; synth -top mac; tee -o mac_v2_stat.rpt stat'`

Try it: Project → Synthesis (Yosys) → import `mac_v1_stat.rpt`, then `mac_v2_stat.rpt` → Compare → Explain with Nemotron.
