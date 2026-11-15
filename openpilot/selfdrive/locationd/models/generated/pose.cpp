#include "pose.h"

namespace {
#define DIM 18
#define EDIM 18
#define MEDIM 18
typedef void (*Hfun)(double *, double *, double *);
const static double MAHA_THRESH_4 = 7.814727903251177;
const static double MAHA_THRESH_10 = 7.814727903251177;
const static double MAHA_THRESH_13 = 7.814727903251177;
const static double MAHA_THRESH_14 = 7.814727903251177;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_5934457951643849053) {
   out_5934457951643849053[0] = delta_x[0] + nom_x[0];
   out_5934457951643849053[1] = delta_x[1] + nom_x[1];
   out_5934457951643849053[2] = delta_x[2] + nom_x[2];
   out_5934457951643849053[3] = delta_x[3] + nom_x[3];
   out_5934457951643849053[4] = delta_x[4] + nom_x[4];
   out_5934457951643849053[5] = delta_x[5] + nom_x[5];
   out_5934457951643849053[6] = delta_x[6] + nom_x[6];
   out_5934457951643849053[7] = delta_x[7] + nom_x[7];
   out_5934457951643849053[8] = delta_x[8] + nom_x[8];
   out_5934457951643849053[9] = delta_x[9] + nom_x[9];
   out_5934457951643849053[10] = delta_x[10] + nom_x[10];
   out_5934457951643849053[11] = delta_x[11] + nom_x[11];
   out_5934457951643849053[12] = delta_x[12] + nom_x[12];
   out_5934457951643849053[13] = delta_x[13] + nom_x[13];
   out_5934457951643849053[14] = delta_x[14] + nom_x[14];
   out_5934457951643849053[15] = delta_x[15] + nom_x[15];
   out_5934457951643849053[16] = delta_x[16] + nom_x[16];
   out_5934457951643849053[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_3684767865165890908) {
   out_3684767865165890908[0] = -nom_x[0] + true_x[0];
   out_3684767865165890908[1] = -nom_x[1] + true_x[1];
   out_3684767865165890908[2] = -nom_x[2] + true_x[2];
   out_3684767865165890908[3] = -nom_x[3] + true_x[3];
   out_3684767865165890908[4] = -nom_x[4] + true_x[4];
   out_3684767865165890908[5] = -nom_x[5] + true_x[5];
   out_3684767865165890908[6] = -nom_x[6] + true_x[6];
   out_3684767865165890908[7] = -nom_x[7] + true_x[7];
   out_3684767865165890908[8] = -nom_x[8] + true_x[8];
   out_3684767865165890908[9] = -nom_x[9] + true_x[9];
   out_3684767865165890908[10] = -nom_x[10] + true_x[10];
   out_3684767865165890908[11] = -nom_x[11] + true_x[11];
   out_3684767865165890908[12] = -nom_x[12] + true_x[12];
   out_3684767865165890908[13] = -nom_x[13] + true_x[13];
   out_3684767865165890908[14] = -nom_x[14] + true_x[14];
   out_3684767865165890908[15] = -nom_x[15] + true_x[15];
   out_3684767865165890908[16] = -nom_x[16] + true_x[16];
   out_3684767865165890908[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_6516592031989874719) {
   out_6516592031989874719[0] = 1.0;
   out_6516592031989874719[1] = 0.0;
   out_6516592031989874719[2] = 0.0;
   out_6516592031989874719[3] = 0.0;
   out_6516592031989874719[4] = 0.0;
   out_6516592031989874719[5] = 0.0;
   out_6516592031989874719[6] = 0.0;
   out_6516592031989874719[7] = 0.0;
   out_6516592031989874719[8] = 0.0;
   out_6516592031989874719[9] = 0.0;
   out_6516592031989874719[10] = 0.0;
   out_6516592031989874719[11] = 0.0;
   out_6516592031989874719[12] = 0.0;
   out_6516592031989874719[13] = 0.0;
   out_6516592031989874719[14] = 0.0;
   out_6516592031989874719[15] = 0.0;
   out_6516592031989874719[16] = 0.0;
   out_6516592031989874719[17] = 0.0;
   out_6516592031989874719[18] = 0.0;
   out_6516592031989874719[19] = 1.0;
   out_6516592031989874719[20] = 0.0;
   out_6516592031989874719[21] = 0.0;
   out_6516592031989874719[22] = 0.0;
   out_6516592031989874719[23] = 0.0;
   out_6516592031989874719[24] = 0.0;
   out_6516592031989874719[25] = 0.0;
   out_6516592031989874719[26] = 0.0;
   out_6516592031989874719[27] = 0.0;
   out_6516592031989874719[28] = 0.0;
   out_6516592031989874719[29] = 0.0;
   out_6516592031989874719[30] = 0.0;
   out_6516592031989874719[31] = 0.0;
   out_6516592031989874719[32] = 0.0;
   out_6516592031989874719[33] = 0.0;
   out_6516592031989874719[34] = 0.0;
   out_6516592031989874719[35] = 0.0;
   out_6516592031989874719[36] = 0.0;
   out_6516592031989874719[37] = 0.0;
   out_6516592031989874719[38] = 1.0;
   out_6516592031989874719[39] = 0.0;
   out_6516592031989874719[40] = 0.0;
   out_6516592031989874719[41] = 0.0;
   out_6516592031989874719[42] = 0.0;
   out_6516592031989874719[43] = 0.0;
   out_6516592031989874719[44] = 0.0;
   out_6516592031989874719[45] = 0.0;
   out_6516592031989874719[46] = 0.0;
   out_6516592031989874719[47] = 0.0;
   out_6516592031989874719[48] = 0.0;
   out_6516592031989874719[49] = 0.0;
   out_6516592031989874719[50] = 0.0;
   out_6516592031989874719[51] = 0.0;
   out_6516592031989874719[52] = 0.0;
   out_6516592031989874719[53] = 0.0;
   out_6516592031989874719[54] = 0.0;
   out_6516592031989874719[55] = 0.0;
   out_6516592031989874719[56] = 0.0;
   out_6516592031989874719[57] = 1.0;
   out_6516592031989874719[58] = 0.0;
   out_6516592031989874719[59] = 0.0;
   out_6516592031989874719[60] = 0.0;
   out_6516592031989874719[61] = 0.0;
   out_6516592031989874719[62] = 0.0;
   out_6516592031989874719[63] = 0.0;
   out_6516592031989874719[64] = 0.0;
   out_6516592031989874719[65] = 0.0;
   out_6516592031989874719[66] = 0.0;
   out_6516592031989874719[67] = 0.0;
   out_6516592031989874719[68] = 0.0;
   out_6516592031989874719[69] = 0.0;
   out_6516592031989874719[70] = 0.0;
   out_6516592031989874719[71] = 0.0;
   out_6516592031989874719[72] = 0.0;
   out_6516592031989874719[73] = 0.0;
   out_6516592031989874719[74] = 0.0;
   out_6516592031989874719[75] = 0.0;
   out_6516592031989874719[76] = 1.0;
   out_6516592031989874719[77] = 0.0;
   out_6516592031989874719[78] = 0.0;
   out_6516592031989874719[79] = 0.0;
   out_6516592031989874719[80] = 0.0;
   out_6516592031989874719[81] = 0.0;
   out_6516592031989874719[82] = 0.0;
   out_6516592031989874719[83] = 0.0;
   out_6516592031989874719[84] = 0.0;
   out_6516592031989874719[85] = 0.0;
   out_6516592031989874719[86] = 0.0;
   out_6516592031989874719[87] = 0.0;
   out_6516592031989874719[88] = 0.0;
   out_6516592031989874719[89] = 0.0;
   out_6516592031989874719[90] = 0.0;
   out_6516592031989874719[91] = 0.0;
   out_6516592031989874719[92] = 0.0;
   out_6516592031989874719[93] = 0.0;
   out_6516592031989874719[94] = 0.0;
   out_6516592031989874719[95] = 1.0;
   out_6516592031989874719[96] = 0.0;
   out_6516592031989874719[97] = 0.0;
   out_6516592031989874719[98] = 0.0;
   out_6516592031989874719[99] = 0.0;
   out_6516592031989874719[100] = 0.0;
   out_6516592031989874719[101] = 0.0;
   out_6516592031989874719[102] = 0.0;
   out_6516592031989874719[103] = 0.0;
   out_6516592031989874719[104] = 0.0;
   out_6516592031989874719[105] = 0.0;
   out_6516592031989874719[106] = 0.0;
   out_6516592031989874719[107] = 0.0;
   out_6516592031989874719[108] = 0.0;
   out_6516592031989874719[109] = 0.0;
   out_6516592031989874719[110] = 0.0;
   out_6516592031989874719[111] = 0.0;
   out_6516592031989874719[112] = 0.0;
   out_6516592031989874719[113] = 0.0;
   out_6516592031989874719[114] = 1.0;
   out_6516592031989874719[115] = 0.0;
   out_6516592031989874719[116] = 0.0;
   out_6516592031989874719[117] = 0.0;
   out_6516592031989874719[118] = 0.0;
   out_6516592031989874719[119] = 0.0;
   out_6516592031989874719[120] = 0.0;
   out_6516592031989874719[121] = 0.0;
   out_6516592031989874719[122] = 0.0;
   out_6516592031989874719[123] = 0.0;
   out_6516592031989874719[124] = 0.0;
   out_6516592031989874719[125] = 0.0;
   out_6516592031989874719[126] = 0.0;
   out_6516592031989874719[127] = 0.0;
   out_6516592031989874719[128] = 0.0;
   out_6516592031989874719[129] = 0.0;
   out_6516592031989874719[130] = 0.0;
   out_6516592031989874719[131] = 0.0;
   out_6516592031989874719[132] = 0.0;
   out_6516592031989874719[133] = 1.0;
   out_6516592031989874719[134] = 0.0;
   out_6516592031989874719[135] = 0.0;
   out_6516592031989874719[136] = 0.0;
   out_6516592031989874719[137] = 0.0;
   out_6516592031989874719[138] = 0.0;
   out_6516592031989874719[139] = 0.0;
   out_6516592031989874719[140] = 0.0;
   out_6516592031989874719[141] = 0.0;
   out_6516592031989874719[142] = 0.0;
   out_6516592031989874719[143] = 0.0;
   out_6516592031989874719[144] = 0.0;
   out_6516592031989874719[145] = 0.0;
   out_6516592031989874719[146] = 0.0;
   out_6516592031989874719[147] = 0.0;
   out_6516592031989874719[148] = 0.0;
   out_6516592031989874719[149] = 0.0;
   out_6516592031989874719[150] = 0.0;
   out_6516592031989874719[151] = 0.0;
   out_6516592031989874719[152] = 1.0;
   out_6516592031989874719[153] = 0.0;
   out_6516592031989874719[154] = 0.0;
   out_6516592031989874719[155] = 0.0;
   out_6516592031989874719[156] = 0.0;
   out_6516592031989874719[157] = 0.0;
   out_6516592031989874719[158] = 0.0;
   out_6516592031989874719[159] = 0.0;
   out_6516592031989874719[160] = 0.0;
   out_6516592031989874719[161] = 0.0;
   out_6516592031989874719[162] = 0.0;
   out_6516592031989874719[163] = 0.0;
   out_6516592031989874719[164] = 0.0;
   out_6516592031989874719[165] = 0.0;
   out_6516592031989874719[166] = 0.0;
   out_6516592031989874719[167] = 0.0;
   out_6516592031989874719[168] = 0.0;
   out_6516592031989874719[169] = 0.0;
   out_6516592031989874719[170] = 0.0;
   out_6516592031989874719[171] = 1.0;
   out_6516592031989874719[172] = 0.0;
   out_6516592031989874719[173] = 0.0;
   out_6516592031989874719[174] = 0.0;
   out_6516592031989874719[175] = 0.0;
   out_6516592031989874719[176] = 0.0;
   out_6516592031989874719[177] = 0.0;
   out_6516592031989874719[178] = 0.0;
   out_6516592031989874719[179] = 0.0;
   out_6516592031989874719[180] = 0.0;
   out_6516592031989874719[181] = 0.0;
   out_6516592031989874719[182] = 0.0;
   out_6516592031989874719[183] = 0.0;
   out_6516592031989874719[184] = 0.0;
   out_6516592031989874719[185] = 0.0;
   out_6516592031989874719[186] = 0.0;
   out_6516592031989874719[187] = 0.0;
   out_6516592031989874719[188] = 0.0;
   out_6516592031989874719[189] = 0.0;
   out_6516592031989874719[190] = 1.0;
   out_6516592031989874719[191] = 0.0;
   out_6516592031989874719[192] = 0.0;
   out_6516592031989874719[193] = 0.0;
   out_6516592031989874719[194] = 0.0;
   out_6516592031989874719[195] = 0.0;
   out_6516592031989874719[196] = 0.0;
   out_6516592031989874719[197] = 0.0;
   out_6516592031989874719[198] = 0.0;
   out_6516592031989874719[199] = 0.0;
   out_6516592031989874719[200] = 0.0;
   out_6516592031989874719[201] = 0.0;
   out_6516592031989874719[202] = 0.0;
   out_6516592031989874719[203] = 0.0;
   out_6516592031989874719[204] = 0.0;
   out_6516592031989874719[205] = 0.0;
   out_6516592031989874719[206] = 0.0;
   out_6516592031989874719[207] = 0.0;
   out_6516592031989874719[208] = 0.0;
   out_6516592031989874719[209] = 1.0;
   out_6516592031989874719[210] = 0.0;
   out_6516592031989874719[211] = 0.0;
   out_6516592031989874719[212] = 0.0;
   out_6516592031989874719[213] = 0.0;
   out_6516592031989874719[214] = 0.0;
   out_6516592031989874719[215] = 0.0;
   out_6516592031989874719[216] = 0.0;
   out_6516592031989874719[217] = 0.0;
   out_6516592031989874719[218] = 0.0;
   out_6516592031989874719[219] = 0.0;
   out_6516592031989874719[220] = 0.0;
   out_6516592031989874719[221] = 0.0;
   out_6516592031989874719[222] = 0.0;
   out_6516592031989874719[223] = 0.0;
   out_6516592031989874719[224] = 0.0;
   out_6516592031989874719[225] = 0.0;
   out_6516592031989874719[226] = 0.0;
   out_6516592031989874719[227] = 0.0;
   out_6516592031989874719[228] = 1.0;
   out_6516592031989874719[229] = 0.0;
   out_6516592031989874719[230] = 0.0;
   out_6516592031989874719[231] = 0.0;
   out_6516592031989874719[232] = 0.0;
   out_6516592031989874719[233] = 0.0;
   out_6516592031989874719[234] = 0.0;
   out_6516592031989874719[235] = 0.0;
   out_6516592031989874719[236] = 0.0;
   out_6516592031989874719[237] = 0.0;
   out_6516592031989874719[238] = 0.0;
   out_6516592031989874719[239] = 0.0;
   out_6516592031989874719[240] = 0.0;
   out_6516592031989874719[241] = 0.0;
   out_6516592031989874719[242] = 0.0;
   out_6516592031989874719[243] = 0.0;
   out_6516592031989874719[244] = 0.0;
   out_6516592031989874719[245] = 0.0;
   out_6516592031989874719[246] = 0.0;
   out_6516592031989874719[247] = 1.0;
   out_6516592031989874719[248] = 0.0;
   out_6516592031989874719[249] = 0.0;
   out_6516592031989874719[250] = 0.0;
   out_6516592031989874719[251] = 0.0;
   out_6516592031989874719[252] = 0.0;
   out_6516592031989874719[253] = 0.0;
   out_6516592031989874719[254] = 0.0;
   out_6516592031989874719[255] = 0.0;
   out_6516592031989874719[256] = 0.0;
   out_6516592031989874719[257] = 0.0;
   out_6516592031989874719[258] = 0.0;
   out_6516592031989874719[259] = 0.0;
   out_6516592031989874719[260] = 0.0;
   out_6516592031989874719[261] = 0.0;
   out_6516592031989874719[262] = 0.0;
   out_6516592031989874719[263] = 0.0;
   out_6516592031989874719[264] = 0.0;
   out_6516592031989874719[265] = 0.0;
   out_6516592031989874719[266] = 1.0;
   out_6516592031989874719[267] = 0.0;
   out_6516592031989874719[268] = 0.0;
   out_6516592031989874719[269] = 0.0;
   out_6516592031989874719[270] = 0.0;
   out_6516592031989874719[271] = 0.0;
   out_6516592031989874719[272] = 0.0;
   out_6516592031989874719[273] = 0.0;
   out_6516592031989874719[274] = 0.0;
   out_6516592031989874719[275] = 0.0;
   out_6516592031989874719[276] = 0.0;
   out_6516592031989874719[277] = 0.0;
   out_6516592031989874719[278] = 0.0;
   out_6516592031989874719[279] = 0.0;
   out_6516592031989874719[280] = 0.0;
   out_6516592031989874719[281] = 0.0;
   out_6516592031989874719[282] = 0.0;
   out_6516592031989874719[283] = 0.0;
   out_6516592031989874719[284] = 0.0;
   out_6516592031989874719[285] = 1.0;
   out_6516592031989874719[286] = 0.0;
   out_6516592031989874719[287] = 0.0;
   out_6516592031989874719[288] = 0.0;
   out_6516592031989874719[289] = 0.0;
   out_6516592031989874719[290] = 0.0;
   out_6516592031989874719[291] = 0.0;
   out_6516592031989874719[292] = 0.0;
   out_6516592031989874719[293] = 0.0;
   out_6516592031989874719[294] = 0.0;
   out_6516592031989874719[295] = 0.0;
   out_6516592031989874719[296] = 0.0;
   out_6516592031989874719[297] = 0.0;
   out_6516592031989874719[298] = 0.0;
   out_6516592031989874719[299] = 0.0;
   out_6516592031989874719[300] = 0.0;
   out_6516592031989874719[301] = 0.0;
   out_6516592031989874719[302] = 0.0;
   out_6516592031989874719[303] = 0.0;
   out_6516592031989874719[304] = 1.0;
   out_6516592031989874719[305] = 0.0;
   out_6516592031989874719[306] = 0.0;
   out_6516592031989874719[307] = 0.0;
   out_6516592031989874719[308] = 0.0;
   out_6516592031989874719[309] = 0.0;
   out_6516592031989874719[310] = 0.0;
   out_6516592031989874719[311] = 0.0;
   out_6516592031989874719[312] = 0.0;
   out_6516592031989874719[313] = 0.0;
   out_6516592031989874719[314] = 0.0;
   out_6516592031989874719[315] = 0.0;
   out_6516592031989874719[316] = 0.0;
   out_6516592031989874719[317] = 0.0;
   out_6516592031989874719[318] = 0.0;
   out_6516592031989874719[319] = 0.0;
   out_6516592031989874719[320] = 0.0;
   out_6516592031989874719[321] = 0.0;
   out_6516592031989874719[322] = 0.0;
   out_6516592031989874719[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_357987265400787918) {
   out_357987265400787918[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_357987265400787918[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_357987265400787918[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_357987265400787918[3] = dt*state[12] + state[3];
   out_357987265400787918[4] = dt*state[13] + state[4];
   out_357987265400787918[5] = dt*state[14] + state[5];
   out_357987265400787918[6] = state[6];
   out_357987265400787918[7] = state[7];
   out_357987265400787918[8] = state[8];
   out_357987265400787918[9] = state[9];
   out_357987265400787918[10] = state[10];
   out_357987265400787918[11] = state[11];
   out_357987265400787918[12] = state[12];
   out_357987265400787918[13] = state[13];
   out_357987265400787918[14] = state[14];
   out_357987265400787918[15] = state[15];
   out_357987265400787918[16] = state[16];
   out_357987265400787918[17] = state[17];
}
void F_fun(double *state, double dt, double *out_6247644819371348210) {
   out_6247644819371348210[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_6247644819371348210[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_6247644819371348210[2] = 0;
   out_6247644819371348210[3] = 0;
   out_6247644819371348210[4] = 0;
   out_6247644819371348210[5] = 0;
   out_6247644819371348210[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_6247644819371348210[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_6247644819371348210[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_6247644819371348210[9] = 0;
   out_6247644819371348210[10] = 0;
   out_6247644819371348210[11] = 0;
   out_6247644819371348210[12] = 0;
   out_6247644819371348210[13] = 0;
   out_6247644819371348210[14] = 0;
   out_6247644819371348210[15] = 0;
   out_6247644819371348210[16] = 0;
   out_6247644819371348210[17] = 0;
   out_6247644819371348210[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_6247644819371348210[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_6247644819371348210[20] = 0;
   out_6247644819371348210[21] = 0;
   out_6247644819371348210[22] = 0;
   out_6247644819371348210[23] = 0;
   out_6247644819371348210[24] = 0;
   out_6247644819371348210[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_6247644819371348210[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_6247644819371348210[27] = 0;
   out_6247644819371348210[28] = 0;
   out_6247644819371348210[29] = 0;
   out_6247644819371348210[30] = 0;
   out_6247644819371348210[31] = 0;
   out_6247644819371348210[32] = 0;
   out_6247644819371348210[33] = 0;
   out_6247644819371348210[34] = 0;
   out_6247644819371348210[35] = 0;
   out_6247644819371348210[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_6247644819371348210[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_6247644819371348210[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_6247644819371348210[39] = 0;
   out_6247644819371348210[40] = 0;
   out_6247644819371348210[41] = 0;
   out_6247644819371348210[42] = 0;
   out_6247644819371348210[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_6247644819371348210[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_6247644819371348210[45] = 0;
   out_6247644819371348210[46] = 0;
   out_6247644819371348210[47] = 0;
   out_6247644819371348210[48] = 0;
   out_6247644819371348210[49] = 0;
   out_6247644819371348210[50] = 0;
   out_6247644819371348210[51] = 0;
   out_6247644819371348210[52] = 0;
   out_6247644819371348210[53] = 0;
   out_6247644819371348210[54] = 0;
   out_6247644819371348210[55] = 0;
   out_6247644819371348210[56] = 0;
   out_6247644819371348210[57] = 1;
   out_6247644819371348210[58] = 0;
   out_6247644819371348210[59] = 0;
   out_6247644819371348210[60] = 0;
   out_6247644819371348210[61] = 0;
   out_6247644819371348210[62] = 0;
   out_6247644819371348210[63] = 0;
   out_6247644819371348210[64] = 0;
   out_6247644819371348210[65] = 0;
   out_6247644819371348210[66] = dt;
   out_6247644819371348210[67] = 0;
   out_6247644819371348210[68] = 0;
   out_6247644819371348210[69] = 0;
   out_6247644819371348210[70] = 0;
   out_6247644819371348210[71] = 0;
   out_6247644819371348210[72] = 0;
   out_6247644819371348210[73] = 0;
   out_6247644819371348210[74] = 0;
   out_6247644819371348210[75] = 0;
   out_6247644819371348210[76] = 1;
   out_6247644819371348210[77] = 0;
   out_6247644819371348210[78] = 0;
   out_6247644819371348210[79] = 0;
   out_6247644819371348210[80] = 0;
   out_6247644819371348210[81] = 0;
   out_6247644819371348210[82] = 0;
   out_6247644819371348210[83] = 0;
   out_6247644819371348210[84] = 0;
   out_6247644819371348210[85] = dt;
   out_6247644819371348210[86] = 0;
   out_6247644819371348210[87] = 0;
   out_6247644819371348210[88] = 0;
   out_6247644819371348210[89] = 0;
   out_6247644819371348210[90] = 0;
   out_6247644819371348210[91] = 0;
   out_6247644819371348210[92] = 0;
   out_6247644819371348210[93] = 0;
   out_6247644819371348210[94] = 0;
   out_6247644819371348210[95] = 1;
   out_6247644819371348210[96] = 0;
   out_6247644819371348210[97] = 0;
   out_6247644819371348210[98] = 0;
   out_6247644819371348210[99] = 0;
   out_6247644819371348210[100] = 0;
   out_6247644819371348210[101] = 0;
   out_6247644819371348210[102] = 0;
   out_6247644819371348210[103] = 0;
   out_6247644819371348210[104] = dt;
   out_6247644819371348210[105] = 0;
   out_6247644819371348210[106] = 0;
   out_6247644819371348210[107] = 0;
   out_6247644819371348210[108] = 0;
   out_6247644819371348210[109] = 0;
   out_6247644819371348210[110] = 0;
   out_6247644819371348210[111] = 0;
   out_6247644819371348210[112] = 0;
   out_6247644819371348210[113] = 0;
   out_6247644819371348210[114] = 1;
   out_6247644819371348210[115] = 0;
   out_6247644819371348210[116] = 0;
   out_6247644819371348210[117] = 0;
   out_6247644819371348210[118] = 0;
   out_6247644819371348210[119] = 0;
   out_6247644819371348210[120] = 0;
   out_6247644819371348210[121] = 0;
   out_6247644819371348210[122] = 0;
   out_6247644819371348210[123] = 0;
   out_6247644819371348210[124] = 0;
   out_6247644819371348210[125] = 0;
   out_6247644819371348210[126] = 0;
   out_6247644819371348210[127] = 0;
   out_6247644819371348210[128] = 0;
   out_6247644819371348210[129] = 0;
   out_6247644819371348210[130] = 0;
   out_6247644819371348210[131] = 0;
   out_6247644819371348210[132] = 0;
   out_6247644819371348210[133] = 1;
   out_6247644819371348210[134] = 0;
   out_6247644819371348210[135] = 0;
   out_6247644819371348210[136] = 0;
   out_6247644819371348210[137] = 0;
   out_6247644819371348210[138] = 0;
   out_6247644819371348210[139] = 0;
   out_6247644819371348210[140] = 0;
   out_6247644819371348210[141] = 0;
   out_6247644819371348210[142] = 0;
   out_6247644819371348210[143] = 0;
   out_6247644819371348210[144] = 0;
   out_6247644819371348210[145] = 0;
   out_6247644819371348210[146] = 0;
   out_6247644819371348210[147] = 0;
   out_6247644819371348210[148] = 0;
   out_6247644819371348210[149] = 0;
   out_6247644819371348210[150] = 0;
   out_6247644819371348210[151] = 0;
   out_6247644819371348210[152] = 1;
   out_6247644819371348210[153] = 0;
   out_6247644819371348210[154] = 0;
   out_6247644819371348210[155] = 0;
   out_6247644819371348210[156] = 0;
   out_6247644819371348210[157] = 0;
   out_6247644819371348210[158] = 0;
   out_6247644819371348210[159] = 0;
   out_6247644819371348210[160] = 0;
   out_6247644819371348210[161] = 0;
   out_6247644819371348210[162] = 0;
   out_6247644819371348210[163] = 0;
   out_6247644819371348210[164] = 0;
   out_6247644819371348210[165] = 0;
   out_6247644819371348210[166] = 0;
   out_6247644819371348210[167] = 0;
   out_6247644819371348210[168] = 0;
   out_6247644819371348210[169] = 0;
   out_6247644819371348210[170] = 0;
   out_6247644819371348210[171] = 1;
   out_6247644819371348210[172] = 0;
   out_6247644819371348210[173] = 0;
   out_6247644819371348210[174] = 0;
   out_6247644819371348210[175] = 0;
   out_6247644819371348210[176] = 0;
   out_6247644819371348210[177] = 0;
   out_6247644819371348210[178] = 0;
   out_6247644819371348210[179] = 0;
   out_6247644819371348210[180] = 0;
   out_6247644819371348210[181] = 0;
   out_6247644819371348210[182] = 0;
   out_6247644819371348210[183] = 0;
   out_6247644819371348210[184] = 0;
   out_6247644819371348210[185] = 0;
   out_6247644819371348210[186] = 0;
   out_6247644819371348210[187] = 0;
   out_6247644819371348210[188] = 0;
   out_6247644819371348210[189] = 0;
   out_6247644819371348210[190] = 1;
   out_6247644819371348210[191] = 0;
   out_6247644819371348210[192] = 0;
   out_6247644819371348210[193] = 0;
   out_6247644819371348210[194] = 0;
   out_6247644819371348210[195] = 0;
   out_6247644819371348210[196] = 0;
   out_6247644819371348210[197] = 0;
   out_6247644819371348210[198] = 0;
   out_6247644819371348210[199] = 0;
   out_6247644819371348210[200] = 0;
   out_6247644819371348210[201] = 0;
   out_6247644819371348210[202] = 0;
   out_6247644819371348210[203] = 0;
   out_6247644819371348210[204] = 0;
   out_6247644819371348210[205] = 0;
   out_6247644819371348210[206] = 0;
   out_6247644819371348210[207] = 0;
   out_6247644819371348210[208] = 0;
   out_6247644819371348210[209] = 1;
   out_6247644819371348210[210] = 0;
   out_6247644819371348210[211] = 0;
   out_6247644819371348210[212] = 0;
   out_6247644819371348210[213] = 0;
   out_6247644819371348210[214] = 0;
   out_6247644819371348210[215] = 0;
   out_6247644819371348210[216] = 0;
   out_6247644819371348210[217] = 0;
   out_6247644819371348210[218] = 0;
   out_6247644819371348210[219] = 0;
   out_6247644819371348210[220] = 0;
   out_6247644819371348210[221] = 0;
   out_6247644819371348210[222] = 0;
   out_6247644819371348210[223] = 0;
   out_6247644819371348210[224] = 0;
   out_6247644819371348210[225] = 0;
   out_6247644819371348210[226] = 0;
   out_6247644819371348210[227] = 0;
   out_6247644819371348210[228] = 1;
   out_6247644819371348210[229] = 0;
   out_6247644819371348210[230] = 0;
   out_6247644819371348210[231] = 0;
   out_6247644819371348210[232] = 0;
   out_6247644819371348210[233] = 0;
   out_6247644819371348210[234] = 0;
   out_6247644819371348210[235] = 0;
   out_6247644819371348210[236] = 0;
   out_6247644819371348210[237] = 0;
   out_6247644819371348210[238] = 0;
   out_6247644819371348210[239] = 0;
   out_6247644819371348210[240] = 0;
   out_6247644819371348210[241] = 0;
   out_6247644819371348210[242] = 0;
   out_6247644819371348210[243] = 0;
   out_6247644819371348210[244] = 0;
   out_6247644819371348210[245] = 0;
   out_6247644819371348210[246] = 0;
   out_6247644819371348210[247] = 1;
   out_6247644819371348210[248] = 0;
   out_6247644819371348210[249] = 0;
   out_6247644819371348210[250] = 0;
   out_6247644819371348210[251] = 0;
   out_6247644819371348210[252] = 0;
   out_6247644819371348210[253] = 0;
   out_6247644819371348210[254] = 0;
   out_6247644819371348210[255] = 0;
   out_6247644819371348210[256] = 0;
   out_6247644819371348210[257] = 0;
   out_6247644819371348210[258] = 0;
   out_6247644819371348210[259] = 0;
   out_6247644819371348210[260] = 0;
   out_6247644819371348210[261] = 0;
   out_6247644819371348210[262] = 0;
   out_6247644819371348210[263] = 0;
   out_6247644819371348210[264] = 0;
   out_6247644819371348210[265] = 0;
   out_6247644819371348210[266] = 1;
   out_6247644819371348210[267] = 0;
   out_6247644819371348210[268] = 0;
   out_6247644819371348210[269] = 0;
   out_6247644819371348210[270] = 0;
   out_6247644819371348210[271] = 0;
   out_6247644819371348210[272] = 0;
   out_6247644819371348210[273] = 0;
   out_6247644819371348210[274] = 0;
   out_6247644819371348210[275] = 0;
   out_6247644819371348210[276] = 0;
   out_6247644819371348210[277] = 0;
   out_6247644819371348210[278] = 0;
   out_6247644819371348210[279] = 0;
   out_6247644819371348210[280] = 0;
   out_6247644819371348210[281] = 0;
   out_6247644819371348210[282] = 0;
   out_6247644819371348210[283] = 0;
   out_6247644819371348210[284] = 0;
   out_6247644819371348210[285] = 1;
   out_6247644819371348210[286] = 0;
   out_6247644819371348210[287] = 0;
   out_6247644819371348210[288] = 0;
   out_6247644819371348210[289] = 0;
   out_6247644819371348210[290] = 0;
   out_6247644819371348210[291] = 0;
   out_6247644819371348210[292] = 0;
   out_6247644819371348210[293] = 0;
   out_6247644819371348210[294] = 0;
   out_6247644819371348210[295] = 0;
   out_6247644819371348210[296] = 0;
   out_6247644819371348210[297] = 0;
   out_6247644819371348210[298] = 0;
   out_6247644819371348210[299] = 0;
   out_6247644819371348210[300] = 0;
   out_6247644819371348210[301] = 0;
   out_6247644819371348210[302] = 0;
   out_6247644819371348210[303] = 0;
   out_6247644819371348210[304] = 1;
   out_6247644819371348210[305] = 0;
   out_6247644819371348210[306] = 0;
   out_6247644819371348210[307] = 0;
   out_6247644819371348210[308] = 0;
   out_6247644819371348210[309] = 0;
   out_6247644819371348210[310] = 0;
   out_6247644819371348210[311] = 0;
   out_6247644819371348210[312] = 0;
   out_6247644819371348210[313] = 0;
   out_6247644819371348210[314] = 0;
   out_6247644819371348210[315] = 0;
   out_6247644819371348210[316] = 0;
   out_6247644819371348210[317] = 0;
   out_6247644819371348210[318] = 0;
   out_6247644819371348210[319] = 0;
   out_6247644819371348210[320] = 0;
   out_6247644819371348210[321] = 0;
   out_6247644819371348210[322] = 0;
   out_6247644819371348210[323] = 1;
}
void h_4(double *state, double *unused, double *out_1318227695036795702) {
   out_1318227695036795702[0] = state[6] + state[9];
   out_1318227695036795702[1] = state[7] + state[10];
   out_1318227695036795702[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_3242369953198925466) {
   out_3242369953198925466[0] = 0;
   out_3242369953198925466[1] = 0;
   out_3242369953198925466[2] = 0;
   out_3242369953198925466[3] = 0;
   out_3242369953198925466[4] = 0;
   out_3242369953198925466[5] = 0;
   out_3242369953198925466[6] = 1;
   out_3242369953198925466[7] = 0;
   out_3242369953198925466[8] = 0;
   out_3242369953198925466[9] = 1;
   out_3242369953198925466[10] = 0;
   out_3242369953198925466[11] = 0;
   out_3242369953198925466[12] = 0;
   out_3242369953198925466[13] = 0;
   out_3242369953198925466[14] = 0;
   out_3242369953198925466[15] = 0;
   out_3242369953198925466[16] = 0;
   out_3242369953198925466[17] = 0;
   out_3242369953198925466[18] = 0;
   out_3242369953198925466[19] = 0;
   out_3242369953198925466[20] = 0;
   out_3242369953198925466[21] = 0;
   out_3242369953198925466[22] = 0;
   out_3242369953198925466[23] = 0;
   out_3242369953198925466[24] = 0;
   out_3242369953198925466[25] = 1;
   out_3242369953198925466[26] = 0;
   out_3242369953198925466[27] = 0;
   out_3242369953198925466[28] = 1;
   out_3242369953198925466[29] = 0;
   out_3242369953198925466[30] = 0;
   out_3242369953198925466[31] = 0;
   out_3242369953198925466[32] = 0;
   out_3242369953198925466[33] = 0;
   out_3242369953198925466[34] = 0;
   out_3242369953198925466[35] = 0;
   out_3242369953198925466[36] = 0;
   out_3242369953198925466[37] = 0;
   out_3242369953198925466[38] = 0;
   out_3242369953198925466[39] = 0;
   out_3242369953198925466[40] = 0;
   out_3242369953198925466[41] = 0;
   out_3242369953198925466[42] = 0;
   out_3242369953198925466[43] = 0;
   out_3242369953198925466[44] = 1;
   out_3242369953198925466[45] = 0;
   out_3242369953198925466[46] = 0;
   out_3242369953198925466[47] = 1;
   out_3242369953198925466[48] = 0;
   out_3242369953198925466[49] = 0;
   out_3242369953198925466[50] = 0;
   out_3242369953198925466[51] = 0;
   out_3242369953198925466[52] = 0;
   out_3242369953198925466[53] = 0;
}
void h_10(double *state, double *unused, double *out_3597588542648254460) {
   out_3597588542648254460[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_3597588542648254460[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_3597588542648254460[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_8062556672432655720) {
   out_8062556672432655720[0] = 0;
   out_8062556672432655720[1] = 9.8100000000000005*cos(state[1]);
   out_8062556672432655720[2] = 0;
   out_8062556672432655720[3] = 0;
   out_8062556672432655720[4] = -state[8];
   out_8062556672432655720[5] = state[7];
   out_8062556672432655720[6] = 0;
   out_8062556672432655720[7] = state[5];
   out_8062556672432655720[8] = -state[4];
   out_8062556672432655720[9] = 0;
   out_8062556672432655720[10] = 0;
   out_8062556672432655720[11] = 0;
   out_8062556672432655720[12] = 1;
   out_8062556672432655720[13] = 0;
   out_8062556672432655720[14] = 0;
   out_8062556672432655720[15] = 1;
   out_8062556672432655720[16] = 0;
   out_8062556672432655720[17] = 0;
   out_8062556672432655720[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_8062556672432655720[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_8062556672432655720[20] = 0;
   out_8062556672432655720[21] = state[8];
   out_8062556672432655720[22] = 0;
   out_8062556672432655720[23] = -state[6];
   out_8062556672432655720[24] = -state[5];
   out_8062556672432655720[25] = 0;
   out_8062556672432655720[26] = state[3];
   out_8062556672432655720[27] = 0;
   out_8062556672432655720[28] = 0;
   out_8062556672432655720[29] = 0;
   out_8062556672432655720[30] = 0;
   out_8062556672432655720[31] = 1;
   out_8062556672432655720[32] = 0;
   out_8062556672432655720[33] = 0;
   out_8062556672432655720[34] = 1;
   out_8062556672432655720[35] = 0;
   out_8062556672432655720[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_8062556672432655720[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_8062556672432655720[38] = 0;
   out_8062556672432655720[39] = -state[7];
   out_8062556672432655720[40] = state[6];
   out_8062556672432655720[41] = 0;
   out_8062556672432655720[42] = state[4];
   out_8062556672432655720[43] = -state[3];
   out_8062556672432655720[44] = 0;
   out_8062556672432655720[45] = 0;
   out_8062556672432655720[46] = 0;
   out_8062556672432655720[47] = 0;
   out_8062556672432655720[48] = 0;
   out_8062556672432655720[49] = 0;
   out_8062556672432655720[50] = 1;
   out_8062556672432655720[51] = 0;
   out_8062556672432655720[52] = 0;
   out_8062556672432655720[53] = 1;
}
void h_13(double *state, double *unused, double *out_6604511232793618697) {
   out_6604511232793618697[0] = state[3];
   out_6604511232793618697[1] = state[4];
   out_6604511232793618697[2] = state[5];
}
void H_13(double *state, double *unused, double *out_7593742912193925221) {
   out_7593742912193925221[0] = 0;
   out_7593742912193925221[1] = 0;
   out_7593742912193925221[2] = 0;
   out_7593742912193925221[3] = 1;
   out_7593742912193925221[4] = 0;
   out_7593742912193925221[5] = 0;
   out_7593742912193925221[6] = 0;
   out_7593742912193925221[7] = 0;
   out_7593742912193925221[8] = 0;
   out_7593742912193925221[9] = 0;
   out_7593742912193925221[10] = 0;
   out_7593742912193925221[11] = 0;
   out_7593742912193925221[12] = 0;
   out_7593742912193925221[13] = 0;
   out_7593742912193925221[14] = 0;
   out_7593742912193925221[15] = 0;
   out_7593742912193925221[16] = 0;
   out_7593742912193925221[17] = 0;
   out_7593742912193925221[18] = 0;
   out_7593742912193925221[19] = 0;
   out_7593742912193925221[20] = 0;
   out_7593742912193925221[21] = 0;
   out_7593742912193925221[22] = 1;
   out_7593742912193925221[23] = 0;
   out_7593742912193925221[24] = 0;
   out_7593742912193925221[25] = 0;
   out_7593742912193925221[26] = 0;
   out_7593742912193925221[27] = 0;
   out_7593742912193925221[28] = 0;
   out_7593742912193925221[29] = 0;
   out_7593742912193925221[30] = 0;
   out_7593742912193925221[31] = 0;
   out_7593742912193925221[32] = 0;
   out_7593742912193925221[33] = 0;
   out_7593742912193925221[34] = 0;
   out_7593742912193925221[35] = 0;
   out_7593742912193925221[36] = 0;
   out_7593742912193925221[37] = 0;
   out_7593742912193925221[38] = 0;
   out_7593742912193925221[39] = 0;
   out_7593742912193925221[40] = 0;
   out_7593742912193925221[41] = 1;
   out_7593742912193925221[42] = 0;
   out_7593742912193925221[43] = 0;
   out_7593742912193925221[44] = 0;
   out_7593742912193925221[45] = 0;
   out_7593742912193925221[46] = 0;
   out_7593742912193925221[47] = 0;
   out_7593742912193925221[48] = 0;
   out_7593742912193925221[49] = 0;
   out_7593742912193925221[50] = 0;
   out_7593742912193925221[51] = 0;
   out_7593742912193925221[52] = 0;
   out_7593742912193925221[53] = 0;
}
void h_14(double *state, double *unused, double *out_1750689771247766537) {
   out_1750689771247766537[0] = state[6];
   out_1750689771247766537[1] = state[7];
   out_1750689771247766537[2] = state[8];
}
void H_14(double *state, double *unused, double *out_7205610809538409995) {
   out_7205610809538409995[0] = 0;
   out_7205610809538409995[1] = 0;
   out_7205610809538409995[2] = 0;
   out_7205610809538409995[3] = 0;
   out_7205610809538409995[4] = 0;
   out_7205610809538409995[5] = 0;
   out_7205610809538409995[6] = 1;
   out_7205610809538409995[7] = 0;
   out_7205610809538409995[8] = 0;
   out_7205610809538409995[9] = 0;
   out_7205610809538409995[10] = 0;
   out_7205610809538409995[11] = 0;
   out_7205610809538409995[12] = 0;
   out_7205610809538409995[13] = 0;
   out_7205610809538409995[14] = 0;
   out_7205610809538409995[15] = 0;
   out_7205610809538409995[16] = 0;
   out_7205610809538409995[17] = 0;
   out_7205610809538409995[18] = 0;
   out_7205610809538409995[19] = 0;
   out_7205610809538409995[20] = 0;
   out_7205610809538409995[21] = 0;
   out_7205610809538409995[22] = 0;
   out_7205610809538409995[23] = 0;
   out_7205610809538409995[24] = 0;
   out_7205610809538409995[25] = 1;
   out_7205610809538409995[26] = 0;
   out_7205610809538409995[27] = 0;
   out_7205610809538409995[28] = 0;
   out_7205610809538409995[29] = 0;
   out_7205610809538409995[30] = 0;
   out_7205610809538409995[31] = 0;
   out_7205610809538409995[32] = 0;
   out_7205610809538409995[33] = 0;
   out_7205610809538409995[34] = 0;
   out_7205610809538409995[35] = 0;
   out_7205610809538409995[36] = 0;
   out_7205610809538409995[37] = 0;
   out_7205610809538409995[38] = 0;
   out_7205610809538409995[39] = 0;
   out_7205610809538409995[40] = 0;
   out_7205610809538409995[41] = 0;
   out_7205610809538409995[42] = 0;
   out_7205610809538409995[43] = 0;
   out_7205610809538409995[44] = 1;
   out_7205610809538409995[45] = 0;
   out_7205610809538409995[46] = 0;
   out_7205610809538409995[47] = 0;
   out_7205610809538409995[48] = 0;
   out_7205610809538409995[49] = 0;
   out_7205610809538409995[50] = 0;
   out_7205610809538409995[51] = 0;
   out_7205610809538409995[52] = 0;
   out_7205610809538409995[53] = 0;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_4, H_4, NULL, in_z, in_R, in_ea, MAHA_THRESH_4);
}
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_10, H_10, NULL, in_z, in_R, in_ea, MAHA_THRESH_10);
}
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_13, H_13, NULL, in_z, in_R, in_ea, MAHA_THRESH_13);
}
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_14, H_14, NULL, in_z, in_R, in_ea, MAHA_THRESH_14);
}
void pose_err_fun(double *nom_x, double *delta_x, double *out_5934457951643849053) {
  err_fun(nom_x, delta_x, out_5934457951643849053);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_3684767865165890908) {
  inv_err_fun(nom_x, true_x, out_3684767865165890908);
}
void pose_H_mod_fun(double *state, double *out_6516592031989874719) {
  H_mod_fun(state, out_6516592031989874719);
}
void pose_f_fun(double *state, double dt, double *out_357987265400787918) {
  f_fun(state,  dt, out_357987265400787918);
}
void pose_F_fun(double *state, double dt, double *out_6247644819371348210) {
  F_fun(state,  dt, out_6247644819371348210);
}
void pose_h_4(double *state, double *unused, double *out_1318227695036795702) {
  h_4(state, unused, out_1318227695036795702);
}
void pose_H_4(double *state, double *unused, double *out_3242369953198925466) {
  H_4(state, unused, out_3242369953198925466);
}
void pose_h_10(double *state, double *unused, double *out_3597588542648254460) {
  h_10(state, unused, out_3597588542648254460);
}
void pose_H_10(double *state, double *unused, double *out_8062556672432655720) {
  H_10(state, unused, out_8062556672432655720);
}
void pose_h_13(double *state, double *unused, double *out_6604511232793618697) {
  h_13(state, unused, out_6604511232793618697);
}
void pose_H_13(double *state, double *unused, double *out_7593742912193925221) {
  H_13(state, unused, out_7593742912193925221);
}
void pose_h_14(double *state, double *unused, double *out_1750689771247766537) {
  h_14(state, unused, out_1750689771247766537);
}
void pose_H_14(double *state, double *unused, double *out_7205610809538409995) {
  H_14(state, unused, out_7205610809538409995);
}
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
}

const EKF pose = {
  .name = "pose",
  .kinds = { 4, 10, 13, 14 },
  .feature_kinds = {  },
  .f_fun = pose_f_fun,
  .F_fun = pose_F_fun,
  .err_fun = pose_err_fun,
  .inv_err_fun = pose_inv_err_fun,
  .H_mod_fun = pose_H_mod_fun,
  .predict = pose_predict,
  .hs = {
    { 4, pose_h_4 },
    { 10, pose_h_10 },
    { 13, pose_h_13 },
    { 14, pose_h_14 },
  },
  .Hs = {
    { 4, pose_H_4 },
    { 10, pose_H_10 },
    { 13, pose_H_13 },
    { 14, pose_H_14 },
  },
  .updates = {
    { 4, pose_update_4 },
    { 10, pose_update_10 },
    { 13, pose_update_13 },
    { 14, pose_update_14 },
  },
  .Hes = {
  },
  .sets = {
  },
  .extra_routines = {
  },
};

ekf_lib_init(pose)
