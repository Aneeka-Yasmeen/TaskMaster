// Synthetic demo design (written for TaskMaster tests/demo; not from any external project).
// v2: same function, product registered first (one pipeline stage).
module mac (input clk, input rst, input [7:0] a, input [7:0] b, output reg [19:0] acc);
  reg [15:0] prod;
  always @(posedge clk) begin
    if (rst) begin prod <= 16'd0; acc <= 20'd0; end
    else begin prod <= a * b; acc <= acc + prod; end
  end
endmodule
