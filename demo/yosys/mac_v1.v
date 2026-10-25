// Synthetic demo design (written for TaskMaster tests/demo; not from any external project).
// v1: 8-bit multiply-accumulate, single cycle.
module mac (input clk, input rst, input [7:0] a, input [7:0] b, output reg [19:0] acc);
  always @(posedge clk) begin
    if (rst) acc <= 20'd0;
    else acc <= acc + a * b;
  end
endmodule
