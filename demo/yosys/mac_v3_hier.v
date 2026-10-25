// Synthetic demo design (written for TaskMaster tests/demo; not from any external project).
// v3: v2 split into a multiplier submodule (hierarchical).
module mult8 (input clk, input [7:0] a, input [7:0] b, output reg [15:0] p);
  always @(posedge clk) p <= a * b;
endmodule
module mac (input clk, input rst, input [7:0] a, input [7:0] b, output reg [19:0] acc);
  wire [15:0] prod;
  mult8 u_mult (.clk(clk), .a(a), .b(b), .p(prod));
  always @(posedge clk) begin
    if (rst) acc <= 20'd0;
    else acc <= acc + prod;
  end
endmodule
