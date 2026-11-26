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
void err_fun(double *nom_x, double *delta_x, double *out_7638121806024428864) {
   out_7638121806024428864[0] = delta_x[0] + nom_x[0];
   out_7638121806024428864[1] = delta_x[1] + nom_x[1];
   out_7638121806024428864[2] = delta_x[2] + nom_x[2];
   out_7638121806024428864[3] = delta_x[3] + nom_x[3];
   out_7638121806024428864[4] = delta_x[4] + nom_x[4];
   out_7638121806024428864[5] = delta_x[5] + nom_x[5];
   out_7638121806024428864[6] = delta_x[6] + nom_x[6];
   out_7638121806024428864[7] = delta_x[7] + nom_x[7];
   out_7638121806024428864[8] = delta_x[8] + nom_x[8];
   out_7638121806024428864[9] = delta_x[9] + nom_x[9];
   out_7638121806024428864[10] = delta_x[10] + nom_x[10];
   out_7638121806024428864[11] = delta_x[11] + nom_x[11];
   out_7638121806024428864[12] = delta_x[12] + nom_x[12];
   out_7638121806024428864[13] = delta_x[13] + nom_x[13];
   out_7638121806024428864[14] = delta_x[14] + nom_x[14];
   out_7638121806024428864[15] = delta_x[15] + nom_x[15];
   out_7638121806024428864[16] = delta_x[16] + nom_x[16];
   out_7638121806024428864[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_7875098923290555577) {
   out_7875098923290555577[0] = -nom_x[0] + true_x[0];
   out_7875098923290555577[1] = -nom_x[1] + true_x[1];
   out_7875098923290555577[2] = -nom_x[2] + true_x[2];
   out_7875098923290555577[3] = -nom_x[3] + true_x[3];
   out_7875098923290555577[4] = -nom_x[4] + true_x[4];
   out_7875098923290555577[5] = -nom_x[5] + true_x[5];
   out_7875098923290555577[6] = -nom_x[6] + true_x[6];
   out_7875098923290555577[7] = -nom_x[7] + true_x[7];
   out_7875098923290555577[8] = -nom_x[8] + true_x[8];
   out_7875098923290555577[9] = -nom_x[9] + true_x[9];
   out_7875098923290555577[10] = -nom_x[10] + true_x[10];
   out_7875098923290555577[11] = -nom_x[11] + true_x[11];
   out_7875098923290555577[12] = -nom_x[12] + true_x[12];
   out_7875098923290555577[13] = -nom_x[13] + true_x[13];
   out_7875098923290555577[14] = -nom_x[14] + true_x[14];
   out_7875098923290555577[15] = -nom_x[15] + true_x[15];
   out_7875098923290555577[16] = -nom_x[16] + true_x[16];
   out_7875098923290555577[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_8951288927873865647) {
   out_8951288927873865647[0] = 1.0;
   out_8951288927873865647[1] = 0.0;
   out_8951288927873865647[2] = 0.0;
   out_8951288927873865647[3] = 0.0;
   out_8951288927873865647[4] = 0.0;
   out_8951288927873865647[5] = 0.0;
   out_8951288927873865647[6] = 0.0;
   out_8951288927873865647[7] = 0.0;
   out_8951288927873865647[8] = 0.0;
   out_8951288927873865647[9] = 0.0;
   out_8951288927873865647[10] = 0.0;
   out_8951288927873865647[11] = 0.0;
   out_8951288927873865647[12] = 0.0;
   out_8951288927873865647[13] = 0.0;
   out_8951288927873865647[14] = 0.0;
   out_8951288927873865647[15] = 0.0;
   out_8951288927873865647[16] = 0.0;
   out_8951288927873865647[17] = 0.0;
   out_8951288927873865647[18] = 0.0;
   out_8951288927873865647[19] = 1.0;
   out_8951288927873865647[20] = 0.0;
   out_8951288927873865647[21] = 0.0;
   out_8951288927873865647[22] = 0.0;
   out_8951288927873865647[23] = 0.0;
   out_8951288927873865647[24] = 0.0;
   out_8951288927873865647[25] = 0.0;
   out_8951288927873865647[26] = 0.0;
   out_8951288927873865647[27] = 0.0;
   out_8951288927873865647[28] = 0.0;
   out_8951288927873865647[29] = 0.0;
   out_8951288927873865647[30] = 0.0;
   out_8951288927873865647[31] = 0.0;
   out_8951288927873865647[32] = 0.0;
   out_8951288927873865647[33] = 0.0;
   out_8951288927873865647[34] = 0.0;
   out_8951288927873865647[35] = 0.0;
   out_8951288927873865647[36] = 0.0;
   out_8951288927873865647[37] = 0.0;
   out_8951288927873865647[38] = 1.0;
   out_8951288927873865647[39] = 0.0;
   out_8951288927873865647[40] = 0.0;
   out_8951288927873865647[41] = 0.0;
   out_8951288927873865647[42] = 0.0;
   out_8951288927873865647[43] = 0.0;
   out_8951288927873865647[44] = 0.0;
   out_8951288927873865647[45] = 0.0;
   out_8951288927873865647[46] = 0.0;
   out_8951288927873865647[47] = 0.0;
   out_8951288927873865647[48] = 0.0;
   out_8951288927873865647[49] = 0.0;
   out_8951288927873865647[50] = 0.0;
   out_8951288927873865647[51] = 0.0;
   out_8951288927873865647[52] = 0.0;
   out_8951288927873865647[53] = 0.0;
   out_8951288927873865647[54] = 0.0;
   out_8951288927873865647[55] = 0.0;
   out_8951288927873865647[56] = 0.0;
   out_8951288927873865647[57] = 1.0;
   out_8951288927873865647[58] = 0.0;
   out_8951288927873865647[59] = 0.0;
   out_8951288927873865647[60] = 0.0;
   out_8951288927873865647[61] = 0.0;
   out_8951288927873865647[62] = 0.0;
   out_8951288927873865647[63] = 0.0;
   out_8951288927873865647[64] = 0.0;
   out_8951288927873865647[65] = 0.0;
   out_8951288927873865647[66] = 0.0;
   out_8951288927873865647[67] = 0.0;
   out_8951288927873865647[68] = 0.0;
   out_8951288927873865647[69] = 0.0;
   out_8951288927873865647[70] = 0.0;
   out_8951288927873865647[71] = 0.0;
   out_8951288927873865647[72] = 0.0;
   out_8951288927873865647[73] = 0.0;
   out_8951288927873865647[74] = 0.0;
   out_8951288927873865647[75] = 0.0;
   out_8951288927873865647[76] = 1.0;
   out_8951288927873865647[77] = 0.0;
   out_8951288927873865647[78] = 0.0;
   out_8951288927873865647[79] = 0.0;
   out_8951288927873865647[80] = 0.0;
   out_8951288927873865647[81] = 0.0;
   out_8951288927873865647[82] = 0.0;
   out_8951288927873865647[83] = 0.0;
   out_8951288927873865647[84] = 0.0;
   out_8951288927873865647[85] = 0.0;
   out_8951288927873865647[86] = 0.0;
   out_8951288927873865647[87] = 0.0;
   out_8951288927873865647[88] = 0.0;
   out_8951288927873865647[89] = 0.0;
   out_8951288927873865647[90] = 0.0;
   out_8951288927873865647[91] = 0.0;
   out_8951288927873865647[92] = 0.0;
   out_8951288927873865647[93] = 0.0;
   out_8951288927873865647[94] = 0.0;
   out_8951288927873865647[95] = 1.0;
   out_8951288927873865647[96] = 0.0;
   out_8951288927873865647[97] = 0.0;
   out_8951288927873865647[98] = 0.0;
   out_8951288927873865647[99] = 0.0;
   out_8951288927873865647[100] = 0.0;
   out_8951288927873865647[101] = 0.0;
   out_8951288927873865647[102] = 0.0;
   out_8951288927873865647[103] = 0.0;
   out_8951288927873865647[104] = 0.0;
   out_8951288927873865647[105] = 0.0;
   out_8951288927873865647[106] = 0.0;
   out_8951288927873865647[107] = 0.0;
   out_8951288927873865647[108] = 0.0;
   out_8951288927873865647[109] = 0.0;
   out_8951288927873865647[110] = 0.0;
   out_8951288927873865647[111] = 0.0;
   out_8951288927873865647[112] = 0.0;
   out_8951288927873865647[113] = 0.0;
   out_8951288927873865647[114] = 1.0;
   out_8951288927873865647[115] = 0.0;
   out_8951288927873865647[116] = 0.0;
   out_8951288927873865647[117] = 0.0;
   out_8951288927873865647[118] = 0.0;
   out_8951288927873865647[119] = 0.0;
   out_8951288927873865647[120] = 0.0;
   out_8951288927873865647[121] = 0.0;
   out_8951288927873865647[122] = 0.0;
   out_8951288927873865647[123] = 0.0;
   out_8951288927873865647[124] = 0.0;
   out_8951288927873865647[125] = 0.0;
   out_8951288927873865647[126] = 0.0;
   out_8951288927873865647[127] = 0.0;
   out_8951288927873865647[128] = 0.0;
   out_8951288927873865647[129] = 0.0;
   out_8951288927873865647[130] = 0.0;
   out_8951288927873865647[131] = 0.0;
   out_8951288927873865647[132] = 0.0;
   out_8951288927873865647[133] = 1.0;
   out_8951288927873865647[134] = 0.0;
   out_8951288927873865647[135] = 0.0;
   out_8951288927873865647[136] = 0.0;
   out_8951288927873865647[137] = 0.0;
   out_8951288927873865647[138] = 0.0;
   out_8951288927873865647[139] = 0.0;
   out_8951288927873865647[140] = 0.0;
   out_8951288927873865647[141] = 0.0;
   out_8951288927873865647[142] = 0.0;
   out_8951288927873865647[143] = 0.0;
   out_8951288927873865647[144] = 0.0;
   out_8951288927873865647[145] = 0.0;
   out_8951288927873865647[146] = 0.0;
   out_8951288927873865647[147] = 0.0;
   out_8951288927873865647[148] = 0.0;
   out_8951288927873865647[149] = 0.0;
   out_8951288927873865647[150] = 0.0;
   out_8951288927873865647[151] = 0.0;
   out_8951288927873865647[152] = 1.0;
   out_8951288927873865647[153] = 0.0;
   out_8951288927873865647[154] = 0.0;
   out_8951288927873865647[155] = 0.0;
   out_8951288927873865647[156] = 0.0;
   out_8951288927873865647[157] = 0.0;
   out_8951288927873865647[158] = 0.0;
   out_8951288927873865647[159] = 0.0;
   out_8951288927873865647[160] = 0.0;
   out_8951288927873865647[161] = 0.0;
   out_8951288927873865647[162] = 0.0;
   out_8951288927873865647[163] = 0.0;
   out_8951288927873865647[164] = 0.0;
   out_8951288927873865647[165] = 0.0;
   out_8951288927873865647[166] = 0.0;
   out_8951288927873865647[167] = 0.0;
   out_8951288927873865647[168] = 0.0;
   out_8951288927873865647[169] = 0.0;
   out_8951288927873865647[170] = 0.0;
   out_8951288927873865647[171] = 1.0;
   out_8951288927873865647[172] = 0.0;
   out_8951288927873865647[173] = 0.0;
   out_8951288927873865647[174] = 0.0;
   out_8951288927873865647[175] = 0.0;
   out_8951288927873865647[176] = 0.0;
   out_8951288927873865647[177] = 0.0;
   out_8951288927873865647[178] = 0.0;
   out_8951288927873865647[179] = 0.0;
   out_8951288927873865647[180] = 0.0;
   out_8951288927873865647[181] = 0.0;
   out_8951288927873865647[182] = 0.0;
   out_8951288927873865647[183] = 0.0;
   out_8951288927873865647[184] = 0.0;
   out_8951288927873865647[185] = 0.0;
   out_8951288927873865647[186] = 0.0;
   out_8951288927873865647[187] = 0.0;
   out_8951288927873865647[188] = 0.0;
   out_8951288927873865647[189] = 0.0;
   out_8951288927873865647[190] = 1.0;
   out_8951288927873865647[191] = 0.0;
   out_8951288927873865647[192] = 0.0;
   out_8951288927873865647[193] = 0.0;
   out_8951288927873865647[194] = 0.0;
   out_8951288927873865647[195] = 0.0;
   out_8951288927873865647[196] = 0.0;
   out_8951288927873865647[197] = 0.0;
   out_8951288927873865647[198] = 0.0;
   out_8951288927873865647[199] = 0.0;
   out_8951288927873865647[200] = 0.0;
   out_8951288927873865647[201] = 0.0;
   out_8951288927873865647[202] = 0.0;
   out_8951288927873865647[203] = 0.0;
   out_8951288927873865647[204] = 0.0;
   out_8951288927873865647[205] = 0.0;
   out_8951288927873865647[206] = 0.0;
   out_8951288927873865647[207] = 0.0;
   out_8951288927873865647[208] = 0.0;
   out_8951288927873865647[209] = 1.0;
   out_8951288927873865647[210] = 0.0;
   out_8951288927873865647[211] = 0.0;
   out_8951288927873865647[212] = 0.0;
   out_8951288927873865647[213] = 0.0;
   out_8951288927873865647[214] = 0.0;
   out_8951288927873865647[215] = 0.0;
   out_8951288927873865647[216] = 0.0;
   out_8951288927873865647[217] = 0.0;
   out_8951288927873865647[218] = 0.0;
   out_8951288927873865647[219] = 0.0;
   out_8951288927873865647[220] = 0.0;
   out_8951288927873865647[221] = 0.0;
   out_8951288927873865647[222] = 0.0;
   out_8951288927873865647[223] = 0.0;
   out_8951288927873865647[224] = 0.0;
   out_8951288927873865647[225] = 0.0;
   out_8951288927873865647[226] = 0.0;
   out_8951288927873865647[227] = 0.0;
   out_8951288927873865647[228] = 1.0;
   out_8951288927873865647[229] = 0.0;
   out_8951288927873865647[230] = 0.0;
   out_8951288927873865647[231] = 0.0;
   out_8951288927873865647[232] = 0.0;
   out_8951288927873865647[233] = 0.0;
   out_8951288927873865647[234] = 0.0;
   out_8951288927873865647[235] = 0.0;
   out_8951288927873865647[236] = 0.0;
   out_8951288927873865647[237] = 0.0;
   out_8951288927873865647[238] = 0.0;
   out_8951288927873865647[239] = 0.0;
   out_8951288927873865647[240] = 0.0;
   out_8951288927873865647[241] = 0.0;
   out_8951288927873865647[242] = 0.0;
   out_8951288927873865647[243] = 0.0;
   out_8951288927873865647[244] = 0.0;
   out_8951288927873865647[245] = 0.0;
   out_8951288927873865647[246] = 0.0;
   out_8951288927873865647[247] = 1.0;
   out_8951288927873865647[248] = 0.0;
   out_8951288927873865647[249] = 0.0;
   out_8951288927873865647[250] = 0.0;
   out_8951288927873865647[251] = 0.0;
   out_8951288927873865647[252] = 0.0;
   out_8951288927873865647[253] = 0.0;
   out_8951288927873865647[254] = 0.0;
   out_8951288927873865647[255] = 0.0;
   out_8951288927873865647[256] = 0.0;
   out_8951288927873865647[257] = 0.0;
   out_8951288927873865647[258] = 0.0;
   out_8951288927873865647[259] = 0.0;
   out_8951288927873865647[260] = 0.0;
   out_8951288927873865647[261] = 0.0;
   out_8951288927873865647[262] = 0.0;
   out_8951288927873865647[263] = 0.0;
   out_8951288927873865647[264] = 0.0;
   out_8951288927873865647[265] = 0.0;
   out_8951288927873865647[266] = 1.0;
   out_8951288927873865647[267] = 0.0;
   out_8951288927873865647[268] = 0.0;
   out_8951288927873865647[269] = 0.0;
   out_8951288927873865647[270] = 0.0;
   out_8951288927873865647[271] = 0.0;
   out_8951288927873865647[272] = 0.0;
   out_8951288927873865647[273] = 0.0;
   out_8951288927873865647[274] = 0.0;
   out_8951288927873865647[275] = 0.0;
   out_8951288927873865647[276] = 0.0;
   out_8951288927873865647[277] = 0.0;
   out_8951288927873865647[278] = 0.0;
   out_8951288927873865647[279] = 0.0;
   out_8951288927873865647[280] = 0.0;
   out_8951288927873865647[281] = 0.0;
   out_8951288927873865647[282] = 0.0;
   out_8951288927873865647[283] = 0.0;
   out_8951288927873865647[284] = 0.0;
   out_8951288927873865647[285] = 1.0;
   out_8951288927873865647[286] = 0.0;
   out_8951288927873865647[287] = 0.0;
   out_8951288927873865647[288] = 0.0;
   out_8951288927873865647[289] = 0.0;
   out_8951288927873865647[290] = 0.0;
   out_8951288927873865647[291] = 0.0;
   out_8951288927873865647[292] = 0.0;
   out_8951288927873865647[293] = 0.0;
   out_8951288927873865647[294] = 0.0;
   out_8951288927873865647[295] = 0.0;
   out_8951288927873865647[296] = 0.0;
   out_8951288927873865647[297] = 0.0;
   out_8951288927873865647[298] = 0.0;
   out_8951288927873865647[299] = 0.0;
   out_8951288927873865647[300] = 0.0;
   out_8951288927873865647[301] = 0.0;
   out_8951288927873865647[302] = 0.0;
   out_8951288927873865647[303] = 0.0;
   out_8951288927873865647[304] = 1.0;
   out_8951288927873865647[305] = 0.0;
   out_8951288927873865647[306] = 0.0;
   out_8951288927873865647[307] = 0.0;
   out_8951288927873865647[308] = 0.0;
   out_8951288927873865647[309] = 0.0;
   out_8951288927873865647[310] = 0.0;
   out_8951288927873865647[311] = 0.0;
   out_8951288927873865647[312] = 0.0;
   out_8951288927873865647[313] = 0.0;
   out_8951288927873865647[314] = 0.0;
   out_8951288927873865647[315] = 0.0;
   out_8951288927873865647[316] = 0.0;
   out_8951288927873865647[317] = 0.0;
   out_8951288927873865647[318] = 0.0;
   out_8951288927873865647[319] = 0.0;
   out_8951288927873865647[320] = 0.0;
   out_8951288927873865647[321] = 0.0;
   out_8951288927873865647[322] = 0.0;
   out_8951288927873865647[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_7132983660684650866) {
   out_7132983660684650866[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_7132983660684650866[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_7132983660684650866[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_7132983660684650866[3] = dt*state[12] + state[3];
   out_7132983660684650866[4] = dt*state[13] + state[4];
   out_7132983660684650866[5] = dt*state[14] + state[5];
   out_7132983660684650866[6] = state[6];
   out_7132983660684650866[7] = state[7];
   out_7132983660684650866[8] = state[8];
   out_7132983660684650866[9] = state[9];
   out_7132983660684650866[10] = state[10];
   out_7132983660684650866[11] = state[11];
   out_7132983660684650866[12] = state[12];
   out_7132983660684650866[13] = state[13];
   out_7132983660684650866[14] = state[14];
   out_7132983660684650866[15] = state[15];
   out_7132983660684650866[16] = state[16];
   out_7132983660684650866[17] = state[17];
}
void F_fun(double *state, double dt, double *out_5301626584540277716) {
   out_5301626584540277716[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5301626584540277716[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5301626584540277716[2] = 0;
   out_5301626584540277716[3] = 0;
   out_5301626584540277716[4] = 0;
   out_5301626584540277716[5] = 0;
   out_5301626584540277716[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5301626584540277716[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5301626584540277716[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_5301626584540277716[9] = 0;
   out_5301626584540277716[10] = 0;
   out_5301626584540277716[11] = 0;
   out_5301626584540277716[12] = 0;
   out_5301626584540277716[13] = 0;
   out_5301626584540277716[14] = 0;
   out_5301626584540277716[15] = 0;
   out_5301626584540277716[16] = 0;
   out_5301626584540277716[17] = 0;
   out_5301626584540277716[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_5301626584540277716[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_5301626584540277716[20] = 0;
   out_5301626584540277716[21] = 0;
   out_5301626584540277716[22] = 0;
   out_5301626584540277716[23] = 0;
   out_5301626584540277716[24] = 0;
   out_5301626584540277716[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_5301626584540277716[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_5301626584540277716[27] = 0;
   out_5301626584540277716[28] = 0;
   out_5301626584540277716[29] = 0;
   out_5301626584540277716[30] = 0;
   out_5301626584540277716[31] = 0;
   out_5301626584540277716[32] = 0;
   out_5301626584540277716[33] = 0;
   out_5301626584540277716[34] = 0;
   out_5301626584540277716[35] = 0;
   out_5301626584540277716[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5301626584540277716[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5301626584540277716[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5301626584540277716[39] = 0;
   out_5301626584540277716[40] = 0;
   out_5301626584540277716[41] = 0;
   out_5301626584540277716[42] = 0;
   out_5301626584540277716[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5301626584540277716[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_5301626584540277716[45] = 0;
   out_5301626584540277716[46] = 0;
   out_5301626584540277716[47] = 0;
   out_5301626584540277716[48] = 0;
   out_5301626584540277716[49] = 0;
   out_5301626584540277716[50] = 0;
   out_5301626584540277716[51] = 0;
   out_5301626584540277716[52] = 0;
   out_5301626584540277716[53] = 0;
   out_5301626584540277716[54] = 0;
   out_5301626584540277716[55] = 0;
   out_5301626584540277716[56] = 0;
   out_5301626584540277716[57] = 1;
   out_5301626584540277716[58] = 0;
   out_5301626584540277716[59] = 0;
   out_5301626584540277716[60] = 0;
   out_5301626584540277716[61] = 0;
   out_5301626584540277716[62] = 0;
   out_5301626584540277716[63] = 0;
   out_5301626584540277716[64] = 0;
   out_5301626584540277716[65] = 0;
   out_5301626584540277716[66] = dt;
   out_5301626584540277716[67] = 0;
   out_5301626584540277716[68] = 0;
   out_5301626584540277716[69] = 0;
   out_5301626584540277716[70] = 0;
   out_5301626584540277716[71] = 0;
   out_5301626584540277716[72] = 0;
   out_5301626584540277716[73] = 0;
   out_5301626584540277716[74] = 0;
   out_5301626584540277716[75] = 0;
   out_5301626584540277716[76] = 1;
   out_5301626584540277716[77] = 0;
   out_5301626584540277716[78] = 0;
   out_5301626584540277716[79] = 0;
   out_5301626584540277716[80] = 0;
   out_5301626584540277716[81] = 0;
   out_5301626584540277716[82] = 0;
   out_5301626584540277716[83] = 0;
   out_5301626584540277716[84] = 0;
   out_5301626584540277716[85] = dt;
   out_5301626584540277716[86] = 0;
   out_5301626584540277716[87] = 0;
   out_5301626584540277716[88] = 0;
   out_5301626584540277716[89] = 0;
   out_5301626584540277716[90] = 0;
   out_5301626584540277716[91] = 0;
   out_5301626584540277716[92] = 0;
   out_5301626584540277716[93] = 0;
   out_5301626584540277716[94] = 0;
   out_5301626584540277716[95] = 1;
   out_5301626584540277716[96] = 0;
   out_5301626584540277716[97] = 0;
   out_5301626584540277716[98] = 0;
   out_5301626584540277716[99] = 0;
   out_5301626584540277716[100] = 0;
   out_5301626584540277716[101] = 0;
   out_5301626584540277716[102] = 0;
   out_5301626584540277716[103] = 0;
   out_5301626584540277716[104] = dt;
   out_5301626584540277716[105] = 0;
   out_5301626584540277716[106] = 0;
   out_5301626584540277716[107] = 0;
   out_5301626584540277716[108] = 0;
   out_5301626584540277716[109] = 0;
   out_5301626584540277716[110] = 0;
   out_5301626584540277716[111] = 0;
   out_5301626584540277716[112] = 0;
   out_5301626584540277716[113] = 0;
   out_5301626584540277716[114] = 1;
   out_5301626584540277716[115] = 0;
   out_5301626584540277716[116] = 0;
   out_5301626584540277716[117] = 0;
   out_5301626584540277716[118] = 0;
   out_5301626584540277716[119] = 0;
   out_5301626584540277716[120] = 0;
   out_5301626584540277716[121] = 0;
   out_5301626584540277716[122] = 0;
   out_5301626584540277716[123] = 0;
   out_5301626584540277716[124] = 0;
   out_5301626584540277716[125] = 0;
   out_5301626584540277716[126] = 0;
   out_5301626584540277716[127] = 0;
   out_5301626584540277716[128] = 0;
   out_5301626584540277716[129] = 0;
   out_5301626584540277716[130] = 0;
   out_5301626584540277716[131] = 0;
   out_5301626584540277716[132] = 0;
   out_5301626584540277716[133] = 1;
   out_5301626584540277716[134] = 0;
   out_5301626584540277716[135] = 0;
   out_5301626584540277716[136] = 0;
   out_5301626584540277716[137] = 0;
   out_5301626584540277716[138] = 0;
   out_5301626584540277716[139] = 0;
   out_5301626584540277716[140] = 0;
   out_5301626584540277716[141] = 0;
   out_5301626584540277716[142] = 0;
   out_5301626584540277716[143] = 0;
   out_5301626584540277716[144] = 0;
   out_5301626584540277716[145] = 0;
   out_5301626584540277716[146] = 0;
   out_5301626584540277716[147] = 0;
   out_5301626584540277716[148] = 0;
   out_5301626584540277716[149] = 0;
   out_5301626584540277716[150] = 0;
   out_5301626584540277716[151] = 0;
   out_5301626584540277716[152] = 1;
   out_5301626584540277716[153] = 0;
   out_5301626584540277716[154] = 0;
   out_5301626584540277716[155] = 0;
   out_5301626584540277716[156] = 0;
   out_5301626584540277716[157] = 0;
   out_5301626584540277716[158] = 0;
   out_5301626584540277716[159] = 0;
   out_5301626584540277716[160] = 0;
   out_5301626584540277716[161] = 0;
   out_5301626584540277716[162] = 0;
   out_5301626584540277716[163] = 0;
   out_5301626584540277716[164] = 0;
   out_5301626584540277716[165] = 0;
   out_5301626584540277716[166] = 0;
   out_5301626584540277716[167] = 0;
   out_5301626584540277716[168] = 0;
   out_5301626584540277716[169] = 0;
   out_5301626584540277716[170] = 0;
   out_5301626584540277716[171] = 1;
   out_5301626584540277716[172] = 0;
   out_5301626584540277716[173] = 0;
   out_5301626584540277716[174] = 0;
   out_5301626584540277716[175] = 0;
   out_5301626584540277716[176] = 0;
   out_5301626584540277716[177] = 0;
   out_5301626584540277716[178] = 0;
   out_5301626584540277716[179] = 0;
   out_5301626584540277716[180] = 0;
   out_5301626584540277716[181] = 0;
   out_5301626584540277716[182] = 0;
   out_5301626584540277716[183] = 0;
   out_5301626584540277716[184] = 0;
   out_5301626584540277716[185] = 0;
   out_5301626584540277716[186] = 0;
   out_5301626584540277716[187] = 0;
   out_5301626584540277716[188] = 0;
   out_5301626584540277716[189] = 0;
   out_5301626584540277716[190] = 1;
   out_5301626584540277716[191] = 0;
   out_5301626584540277716[192] = 0;
   out_5301626584540277716[193] = 0;
   out_5301626584540277716[194] = 0;
   out_5301626584540277716[195] = 0;
   out_5301626584540277716[196] = 0;
   out_5301626584540277716[197] = 0;
   out_5301626584540277716[198] = 0;
   out_5301626584540277716[199] = 0;
   out_5301626584540277716[200] = 0;
   out_5301626584540277716[201] = 0;
   out_5301626584540277716[202] = 0;
   out_5301626584540277716[203] = 0;
   out_5301626584540277716[204] = 0;
   out_5301626584540277716[205] = 0;
   out_5301626584540277716[206] = 0;
   out_5301626584540277716[207] = 0;
   out_5301626584540277716[208] = 0;
   out_5301626584540277716[209] = 1;
   out_5301626584540277716[210] = 0;
   out_5301626584540277716[211] = 0;
   out_5301626584540277716[212] = 0;
   out_5301626584540277716[213] = 0;
   out_5301626584540277716[214] = 0;
   out_5301626584540277716[215] = 0;
   out_5301626584540277716[216] = 0;
   out_5301626584540277716[217] = 0;
   out_5301626584540277716[218] = 0;
   out_5301626584540277716[219] = 0;
   out_5301626584540277716[220] = 0;
   out_5301626584540277716[221] = 0;
   out_5301626584540277716[222] = 0;
   out_5301626584540277716[223] = 0;
   out_5301626584540277716[224] = 0;
   out_5301626584540277716[225] = 0;
   out_5301626584540277716[226] = 0;
   out_5301626584540277716[227] = 0;
   out_5301626584540277716[228] = 1;
   out_5301626584540277716[229] = 0;
   out_5301626584540277716[230] = 0;
   out_5301626584540277716[231] = 0;
   out_5301626584540277716[232] = 0;
   out_5301626584540277716[233] = 0;
   out_5301626584540277716[234] = 0;
   out_5301626584540277716[235] = 0;
   out_5301626584540277716[236] = 0;
   out_5301626584540277716[237] = 0;
   out_5301626584540277716[238] = 0;
   out_5301626584540277716[239] = 0;
   out_5301626584540277716[240] = 0;
   out_5301626584540277716[241] = 0;
   out_5301626584540277716[242] = 0;
   out_5301626584540277716[243] = 0;
   out_5301626584540277716[244] = 0;
   out_5301626584540277716[245] = 0;
   out_5301626584540277716[246] = 0;
   out_5301626584540277716[247] = 1;
   out_5301626584540277716[248] = 0;
   out_5301626584540277716[249] = 0;
   out_5301626584540277716[250] = 0;
   out_5301626584540277716[251] = 0;
   out_5301626584540277716[252] = 0;
   out_5301626584540277716[253] = 0;
   out_5301626584540277716[254] = 0;
   out_5301626584540277716[255] = 0;
   out_5301626584540277716[256] = 0;
   out_5301626584540277716[257] = 0;
   out_5301626584540277716[258] = 0;
   out_5301626584540277716[259] = 0;
   out_5301626584540277716[260] = 0;
   out_5301626584540277716[261] = 0;
   out_5301626584540277716[262] = 0;
   out_5301626584540277716[263] = 0;
   out_5301626584540277716[264] = 0;
   out_5301626584540277716[265] = 0;
   out_5301626584540277716[266] = 1;
   out_5301626584540277716[267] = 0;
   out_5301626584540277716[268] = 0;
   out_5301626584540277716[269] = 0;
   out_5301626584540277716[270] = 0;
   out_5301626584540277716[271] = 0;
   out_5301626584540277716[272] = 0;
   out_5301626584540277716[273] = 0;
   out_5301626584540277716[274] = 0;
   out_5301626584540277716[275] = 0;
   out_5301626584540277716[276] = 0;
   out_5301626584540277716[277] = 0;
   out_5301626584540277716[278] = 0;
   out_5301626584540277716[279] = 0;
   out_5301626584540277716[280] = 0;
   out_5301626584540277716[281] = 0;
   out_5301626584540277716[282] = 0;
   out_5301626584540277716[283] = 0;
   out_5301626584540277716[284] = 0;
   out_5301626584540277716[285] = 1;
   out_5301626584540277716[286] = 0;
   out_5301626584540277716[287] = 0;
   out_5301626584540277716[288] = 0;
   out_5301626584540277716[289] = 0;
   out_5301626584540277716[290] = 0;
   out_5301626584540277716[291] = 0;
   out_5301626584540277716[292] = 0;
   out_5301626584540277716[293] = 0;
   out_5301626584540277716[294] = 0;
   out_5301626584540277716[295] = 0;
   out_5301626584540277716[296] = 0;
   out_5301626584540277716[297] = 0;
   out_5301626584540277716[298] = 0;
   out_5301626584540277716[299] = 0;
   out_5301626584540277716[300] = 0;
   out_5301626584540277716[301] = 0;
   out_5301626584540277716[302] = 0;
   out_5301626584540277716[303] = 0;
   out_5301626584540277716[304] = 1;
   out_5301626584540277716[305] = 0;
   out_5301626584540277716[306] = 0;
   out_5301626584540277716[307] = 0;
   out_5301626584540277716[308] = 0;
   out_5301626584540277716[309] = 0;
   out_5301626584540277716[310] = 0;
   out_5301626584540277716[311] = 0;
   out_5301626584540277716[312] = 0;
   out_5301626584540277716[313] = 0;
   out_5301626584540277716[314] = 0;
   out_5301626584540277716[315] = 0;
   out_5301626584540277716[316] = 0;
   out_5301626584540277716[317] = 0;
   out_5301626584540277716[318] = 0;
   out_5301626584540277716[319] = 0;
   out_5301626584540277716[320] = 0;
   out_5301626584540277716[321] = 0;
   out_5301626584540277716[322] = 0;
   out_5301626584540277716[323] = 1;
}
void h_4(double *state, double *unused, double *out_1649115856604052289) {
   out_1649115856604052289[0] = state[6] + state[9];
   out_1649115856604052289[1] = state[7] + state[10];
   out_1649115856604052289[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_7039102026818812520) {
   out_7039102026818812520[0] = 0;
   out_7039102026818812520[1] = 0;
   out_7039102026818812520[2] = 0;
   out_7039102026818812520[3] = 0;
   out_7039102026818812520[4] = 0;
   out_7039102026818812520[5] = 0;
   out_7039102026818812520[6] = 1;
   out_7039102026818812520[7] = 0;
   out_7039102026818812520[8] = 0;
   out_7039102026818812520[9] = 1;
   out_7039102026818812520[10] = 0;
   out_7039102026818812520[11] = 0;
   out_7039102026818812520[12] = 0;
   out_7039102026818812520[13] = 0;
   out_7039102026818812520[14] = 0;
   out_7039102026818812520[15] = 0;
   out_7039102026818812520[16] = 0;
   out_7039102026818812520[17] = 0;
   out_7039102026818812520[18] = 0;
   out_7039102026818812520[19] = 0;
   out_7039102026818812520[20] = 0;
   out_7039102026818812520[21] = 0;
   out_7039102026818812520[22] = 0;
   out_7039102026818812520[23] = 0;
   out_7039102026818812520[24] = 0;
   out_7039102026818812520[25] = 1;
   out_7039102026818812520[26] = 0;
   out_7039102026818812520[27] = 0;
   out_7039102026818812520[28] = 1;
   out_7039102026818812520[29] = 0;
   out_7039102026818812520[30] = 0;
   out_7039102026818812520[31] = 0;
   out_7039102026818812520[32] = 0;
   out_7039102026818812520[33] = 0;
   out_7039102026818812520[34] = 0;
   out_7039102026818812520[35] = 0;
   out_7039102026818812520[36] = 0;
   out_7039102026818812520[37] = 0;
   out_7039102026818812520[38] = 0;
   out_7039102026818812520[39] = 0;
   out_7039102026818812520[40] = 0;
   out_7039102026818812520[41] = 0;
   out_7039102026818812520[42] = 0;
   out_7039102026818812520[43] = 0;
   out_7039102026818812520[44] = 1;
   out_7039102026818812520[45] = 0;
   out_7039102026818812520[46] = 0;
   out_7039102026818812520[47] = 1;
   out_7039102026818812520[48] = 0;
   out_7039102026818812520[49] = 0;
   out_7039102026818812520[50] = 0;
   out_7039102026818812520[51] = 0;
   out_7039102026818812520[52] = 0;
   out_7039102026818812520[53] = 0;
}
void h_10(double *state, double *unused, double *out_1675122934588286079) {
   out_1675122934588286079[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_1675122934588286079[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_1675122934588286079[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_8074540264726699631) {
   out_8074540264726699631[0] = 0;
   out_8074540264726699631[1] = 9.8100000000000005*cos(state[1]);
   out_8074540264726699631[2] = 0;
   out_8074540264726699631[3] = 0;
   out_8074540264726699631[4] = -state[8];
   out_8074540264726699631[5] = state[7];
   out_8074540264726699631[6] = 0;
   out_8074540264726699631[7] = state[5];
   out_8074540264726699631[8] = -state[4];
   out_8074540264726699631[9] = 0;
   out_8074540264726699631[10] = 0;
   out_8074540264726699631[11] = 0;
   out_8074540264726699631[12] = 1;
   out_8074540264726699631[13] = 0;
   out_8074540264726699631[14] = 0;
   out_8074540264726699631[15] = 1;
   out_8074540264726699631[16] = 0;
   out_8074540264726699631[17] = 0;
   out_8074540264726699631[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_8074540264726699631[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_8074540264726699631[20] = 0;
   out_8074540264726699631[21] = state[8];
   out_8074540264726699631[22] = 0;
   out_8074540264726699631[23] = -state[6];
   out_8074540264726699631[24] = -state[5];
   out_8074540264726699631[25] = 0;
   out_8074540264726699631[26] = state[3];
   out_8074540264726699631[27] = 0;
   out_8074540264726699631[28] = 0;
   out_8074540264726699631[29] = 0;
   out_8074540264726699631[30] = 0;
   out_8074540264726699631[31] = 1;
   out_8074540264726699631[32] = 0;
   out_8074540264726699631[33] = 0;
   out_8074540264726699631[34] = 1;
   out_8074540264726699631[35] = 0;
   out_8074540264726699631[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_8074540264726699631[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_8074540264726699631[38] = 0;
   out_8074540264726699631[39] = -state[7];
   out_8074540264726699631[40] = state[6];
   out_8074540264726699631[41] = 0;
   out_8074540264726699631[42] = state[4];
   out_8074540264726699631[43] = -state[3];
   out_8074540264726699631[44] = 0;
   out_8074540264726699631[45] = 0;
   out_8074540264726699631[46] = 0;
   out_8074540264726699631[47] = 0;
   out_8074540264726699631[48] = 0;
   out_8074540264726699631[49] = 0;
   out_8074540264726699631[50] = 1;
   out_8074540264726699631[51] = 0;
   out_8074540264726699631[52] = 0;
   out_8074540264726699631[53] = 1;
}
void h_13(double *state, double *unused, double *out_5348779440595545487) {
   out_5348779440595545487[0] = state[3];
   out_5348779440595545487[1] = state[4];
   out_5348779440595545487[2] = state[5];
}
void H_13(double *state, double *unused, double *out_3826828201486479719) {
   out_3826828201486479719[0] = 0;
   out_3826828201486479719[1] = 0;
   out_3826828201486479719[2] = 0;
   out_3826828201486479719[3] = 1;
   out_3826828201486479719[4] = 0;
   out_3826828201486479719[5] = 0;
   out_3826828201486479719[6] = 0;
   out_3826828201486479719[7] = 0;
   out_3826828201486479719[8] = 0;
   out_3826828201486479719[9] = 0;
   out_3826828201486479719[10] = 0;
   out_3826828201486479719[11] = 0;
   out_3826828201486479719[12] = 0;
   out_3826828201486479719[13] = 0;
   out_3826828201486479719[14] = 0;
   out_3826828201486479719[15] = 0;
   out_3826828201486479719[16] = 0;
   out_3826828201486479719[17] = 0;
   out_3826828201486479719[18] = 0;
   out_3826828201486479719[19] = 0;
   out_3826828201486479719[20] = 0;
   out_3826828201486479719[21] = 0;
   out_3826828201486479719[22] = 1;
   out_3826828201486479719[23] = 0;
   out_3826828201486479719[24] = 0;
   out_3826828201486479719[25] = 0;
   out_3826828201486479719[26] = 0;
   out_3826828201486479719[27] = 0;
   out_3826828201486479719[28] = 0;
   out_3826828201486479719[29] = 0;
   out_3826828201486479719[30] = 0;
   out_3826828201486479719[31] = 0;
   out_3826828201486479719[32] = 0;
   out_3826828201486479719[33] = 0;
   out_3826828201486479719[34] = 0;
   out_3826828201486479719[35] = 0;
   out_3826828201486479719[36] = 0;
   out_3826828201486479719[37] = 0;
   out_3826828201486479719[38] = 0;
   out_3826828201486479719[39] = 0;
   out_3826828201486479719[40] = 0;
   out_3826828201486479719[41] = 1;
   out_3826828201486479719[42] = 0;
   out_3826828201486479719[43] = 0;
   out_3826828201486479719[44] = 0;
   out_3826828201486479719[45] = 0;
   out_3826828201486479719[46] = 0;
   out_3826828201486479719[47] = 0;
   out_3826828201486479719[48] = 0;
   out_3826828201486479719[49] = 0;
   out_3826828201486479719[50] = 0;
   out_3826828201486479719[51] = 0;
   out_3826828201486479719[52] = 0;
   out_3826828201486479719[53] = 0;
}
void h_14(double *state, double *unused, double *out_8398073438339046034) {
   out_8398073438339046034[0] = state[6];
   out_8398073438339046034[1] = state[7];
   out_8398073438339046034[2] = state[8];
}
void H_14(double *state, double *unused, double *out_3075861170479327991) {
   out_3075861170479327991[0] = 0;
   out_3075861170479327991[1] = 0;
   out_3075861170479327991[2] = 0;
   out_3075861170479327991[3] = 0;
   out_3075861170479327991[4] = 0;
   out_3075861170479327991[5] = 0;
   out_3075861170479327991[6] = 1;
   out_3075861170479327991[7] = 0;
   out_3075861170479327991[8] = 0;
   out_3075861170479327991[9] = 0;
   out_3075861170479327991[10] = 0;
   out_3075861170479327991[11] = 0;
   out_3075861170479327991[12] = 0;
   out_3075861170479327991[13] = 0;
   out_3075861170479327991[14] = 0;
   out_3075861170479327991[15] = 0;
   out_3075861170479327991[16] = 0;
   out_3075861170479327991[17] = 0;
   out_3075861170479327991[18] = 0;
   out_3075861170479327991[19] = 0;
   out_3075861170479327991[20] = 0;
   out_3075861170479327991[21] = 0;
   out_3075861170479327991[22] = 0;
   out_3075861170479327991[23] = 0;
   out_3075861170479327991[24] = 0;
   out_3075861170479327991[25] = 1;
   out_3075861170479327991[26] = 0;
   out_3075861170479327991[27] = 0;
   out_3075861170479327991[28] = 0;
   out_3075861170479327991[29] = 0;
   out_3075861170479327991[30] = 0;
   out_3075861170479327991[31] = 0;
   out_3075861170479327991[32] = 0;
   out_3075861170479327991[33] = 0;
   out_3075861170479327991[34] = 0;
   out_3075861170479327991[35] = 0;
   out_3075861170479327991[36] = 0;
   out_3075861170479327991[37] = 0;
   out_3075861170479327991[38] = 0;
   out_3075861170479327991[39] = 0;
   out_3075861170479327991[40] = 0;
   out_3075861170479327991[41] = 0;
   out_3075861170479327991[42] = 0;
   out_3075861170479327991[43] = 0;
   out_3075861170479327991[44] = 1;
   out_3075861170479327991[45] = 0;
   out_3075861170479327991[46] = 0;
   out_3075861170479327991[47] = 0;
   out_3075861170479327991[48] = 0;
   out_3075861170479327991[49] = 0;
   out_3075861170479327991[50] = 0;
   out_3075861170479327991[51] = 0;
   out_3075861170479327991[52] = 0;
   out_3075861170479327991[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_7638121806024428864) {
  err_fun(nom_x, delta_x, out_7638121806024428864);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_7875098923290555577) {
  inv_err_fun(nom_x, true_x, out_7875098923290555577);
}
void pose_H_mod_fun(double *state, double *out_8951288927873865647) {
  H_mod_fun(state, out_8951288927873865647);
}
void pose_f_fun(double *state, double dt, double *out_7132983660684650866) {
  f_fun(state,  dt, out_7132983660684650866);
}
void pose_F_fun(double *state, double dt, double *out_5301626584540277716) {
  F_fun(state,  dt, out_5301626584540277716);
}
void pose_h_4(double *state, double *unused, double *out_1649115856604052289) {
  h_4(state, unused, out_1649115856604052289);
}
void pose_H_4(double *state, double *unused, double *out_7039102026818812520) {
  H_4(state, unused, out_7039102026818812520);
}
void pose_h_10(double *state, double *unused, double *out_1675122934588286079) {
  h_10(state, unused, out_1675122934588286079);
}
void pose_H_10(double *state, double *unused, double *out_8074540264726699631) {
  H_10(state, unused, out_8074540264726699631);
}
void pose_h_13(double *state, double *unused, double *out_5348779440595545487) {
  h_13(state, unused, out_5348779440595545487);
}
void pose_H_13(double *state, double *unused, double *out_3826828201486479719) {
  H_13(state, unused, out_3826828201486479719);
}
void pose_h_14(double *state, double *unused, double *out_8398073438339046034) {
  h_14(state, unused, out_8398073438339046034);
}
void pose_H_14(double *state, double *unused, double *out_3075861170479327991) {
  H_14(state, unused, out_3075861170479327991);
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
