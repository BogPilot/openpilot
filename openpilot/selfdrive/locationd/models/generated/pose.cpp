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
void err_fun(double *nom_x, double *delta_x, double *out_8954543502953545600) {
   out_8954543502953545600[0] = delta_x[0] + nom_x[0];
   out_8954543502953545600[1] = delta_x[1] + nom_x[1];
   out_8954543502953545600[2] = delta_x[2] + nom_x[2];
   out_8954543502953545600[3] = delta_x[3] + nom_x[3];
   out_8954543502953545600[4] = delta_x[4] + nom_x[4];
   out_8954543502953545600[5] = delta_x[5] + nom_x[5];
   out_8954543502953545600[6] = delta_x[6] + nom_x[6];
   out_8954543502953545600[7] = delta_x[7] + nom_x[7];
   out_8954543502953545600[8] = delta_x[8] + nom_x[8];
   out_8954543502953545600[9] = delta_x[9] + nom_x[9];
   out_8954543502953545600[10] = delta_x[10] + nom_x[10];
   out_8954543502953545600[11] = delta_x[11] + nom_x[11];
   out_8954543502953545600[12] = delta_x[12] + nom_x[12];
   out_8954543502953545600[13] = delta_x[13] + nom_x[13];
   out_8954543502953545600[14] = delta_x[14] + nom_x[14];
   out_8954543502953545600[15] = delta_x[15] + nom_x[15];
   out_8954543502953545600[16] = delta_x[16] + nom_x[16];
   out_8954543502953545600[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_4429120357540117455) {
   out_4429120357540117455[0] = -nom_x[0] + true_x[0];
   out_4429120357540117455[1] = -nom_x[1] + true_x[1];
   out_4429120357540117455[2] = -nom_x[2] + true_x[2];
   out_4429120357540117455[3] = -nom_x[3] + true_x[3];
   out_4429120357540117455[4] = -nom_x[4] + true_x[4];
   out_4429120357540117455[5] = -nom_x[5] + true_x[5];
   out_4429120357540117455[6] = -nom_x[6] + true_x[6];
   out_4429120357540117455[7] = -nom_x[7] + true_x[7];
   out_4429120357540117455[8] = -nom_x[8] + true_x[8];
   out_4429120357540117455[9] = -nom_x[9] + true_x[9];
   out_4429120357540117455[10] = -nom_x[10] + true_x[10];
   out_4429120357540117455[11] = -nom_x[11] + true_x[11];
   out_4429120357540117455[12] = -nom_x[12] + true_x[12];
   out_4429120357540117455[13] = -nom_x[13] + true_x[13];
   out_4429120357540117455[14] = -nom_x[14] + true_x[14];
   out_4429120357540117455[15] = -nom_x[15] + true_x[15];
   out_4429120357540117455[16] = -nom_x[16] + true_x[16];
   out_4429120357540117455[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_230881002087446555) {
   out_230881002087446555[0] = 1.0;
   out_230881002087446555[1] = 0.0;
   out_230881002087446555[2] = 0.0;
   out_230881002087446555[3] = 0.0;
   out_230881002087446555[4] = 0.0;
   out_230881002087446555[5] = 0.0;
   out_230881002087446555[6] = 0.0;
   out_230881002087446555[7] = 0.0;
   out_230881002087446555[8] = 0.0;
   out_230881002087446555[9] = 0.0;
   out_230881002087446555[10] = 0.0;
   out_230881002087446555[11] = 0.0;
   out_230881002087446555[12] = 0.0;
   out_230881002087446555[13] = 0.0;
   out_230881002087446555[14] = 0.0;
   out_230881002087446555[15] = 0.0;
   out_230881002087446555[16] = 0.0;
   out_230881002087446555[17] = 0.0;
   out_230881002087446555[18] = 0.0;
   out_230881002087446555[19] = 1.0;
   out_230881002087446555[20] = 0.0;
   out_230881002087446555[21] = 0.0;
   out_230881002087446555[22] = 0.0;
   out_230881002087446555[23] = 0.0;
   out_230881002087446555[24] = 0.0;
   out_230881002087446555[25] = 0.0;
   out_230881002087446555[26] = 0.0;
   out_230881002087446555[27] = 0.0;
   out_230881002087446555[28] = 0.0;
   out_230881002087446555[29] = 0.0;
   out_230881002087446555[30] = 0.0;
   out_230881002087446555[31] = 0.0;
   out_230881002087446555[32] = 0.0;
   out_230881002087446555[33] = 0.0;
   out_230881002087446555[34] = 0.0;
   out_230881002087446555[35] = 0.0;
   out_230881002087446555[36] = 0.0;
   out_230881002087446555[37] = 0.0;
   out_230881002087446555[38] = 1.0;
   out_230881002087446555[39] = 0.0;
   out_230881002087446555[40] = 0.0;
   out_230881002087446555[41] = 0.0;
   out_230881002087446555[42] = 0.0;
   out_230881002087446555[43] = 0.0;
   out_230881002087446555[44] = 0.0;
   out_230881002087446555[45] = 0.0;
   out_230881002087446555[46] = 0.0;
   out_230881002087446555[47] = 0.0;
   out_230881002087446555[48] = 0.0;
   out_230881002087446555[49] = 0.0;
   out_230881002087446555[50] = 0.0;
   out_230881002087446555[51] = 0.0;
   out_230881002087446555[52] = 0.0;
   out_230881002087446555[53] = 0.0;
   out_230881002087446555[54] = 0.0;
   out_230881002087446555[55] = 0.0;
   out_230881002087446555[56] = 0.0;
   out_230881002087446555[57] = 1.0;
   out_230881002087446555[58] = 0.0;
   out_230881002087446555[59] = 0.0;
   out_230881002087446555[60] = 0.0;
   out_230881002087446555[61] = 0.0;
   out_230881002087446555[62] = 0.0;
   out_230881002087446555[63] = 0.0;
   out_230881002087446555[64] = 0.0;
   out_230881002087446555[65] = 0.0;
   out_230881002087446555[66] = 0.0;
   out_230881002087446555[67] = 0.0;
   out_230881002087446555[68] = 0.0;
   out_230881002087446555[69] = 0.0;
   out_230881002087446555[70] = 0.0;
   out_230881002087446555[71] = 0.0;
   out_230881002087446555[72] = 0.0;
   out_230881002087446555[73] = 0.0;
   out_230881002087446555[74] = 0.0;
   out_230881002087446555[75] = 0.0;
   out_230881002087446555[76] = 1.0;
   out_230881002087446555[77] = 0.0;
   out_230881002087446555[78] = 0.0;
   out_230881002087446555[79] = 0.0;
   out_230881002087446555[80] = 0.0;
   out_230881002087446555[81] = 0.0;
   out_230881002087446555[82] = 0.0;
   out_230881002087446555[83] = 0.0;
   out_230881002087446555[84] = 0.0;
   out_230881002087446555[85] = 0.0;
   out_230881002087446555[86] = 0.0;
   out_230881002087446555[87] = 0.0;
   out_230881002087446555[88] = 0.0;
   out_230881002087446555[89] = 0.0;
   out_230881002087446555[90] = 0.0;
   out_230881002087446555[91] = 0.0;
   out_230881002087446555[92] = 0.0;
   out_230881002087446555[93] = 0.0;
   out_230881002087446555[94] = 0.0;
   out_230881002087446555[95] = 1.0;
   out_230881002087446555[96] = 0.0;
   out_230881002087446555[97] = 0.0;
   out_230881002087446555[98] = 0.0;
   out_230881002087446555[99] = 0.0;
   out_230881002087446555[100] = 0.0;
   out_230881002087446555[101] = 0.0;
   out_230881002087446555[102] = 0.0;
   out_230881002087446555[103] = 0.0;
   out_230881002087446555[104] = 0.0;
   out_230881002087446555[105] = 0.0;
   out_230881002087446555[106] = 0.0;
   out_230881002087446555[107] = 0.0;
   out_230881002087446555[108] = 0.0;
   out_230881002087446555[109] = 0.0;
   out_230881002087446555[110] = 0.0;
   out_230881002087446555[111] = 0.0;
   out_230881002087446555[112] = 0.0;
   out_230881002087446555[113] = 0.0;
   out_230881002087446555[114] = 1.0;
   out_230881002087446555[115] = 0.0;
   out_230881002087446555[116] = 0.0;
   out_230881002087446555[117] = 0.0;
   out_230881002087446555[118] = 0.0;
   out_230881002087446555[119] = 0.0;
   out_230881002087446555[120] = 0.0;
   out_230881002087446555[121] = 0.0;
   out_230881002087446555[122] = 0.0;
   out_230881002087446555[123] = 0.0;
   out_230881002087446555[124] = 0.0;
   out_230881002087446555[125] = 0.0;
   out_230881002087446555[126] = 0.0;
   out_230881002087446555[127] = 0.0;
   out_230881002087446555[128] = 0.0;
   out_230881002087446555[129] = 0.0;
   out_230881002087446555[130] = 0.0;
   out_230881002087446555[131] = 0.0;
   out_230881002087446555[132] = 0.0;
   out_230881002087446555[133] = 1.0;
   out_230881002087446555[134] = 0.0;
   out_230881002087446555[135] = 0.0;
   out_230881002087446555[136] = 0.0;
   out_230881002087446555[137] = 0.0;
   out_230881002087446555[138] = 0.0;
   out_230881002087446555[139] = 0.0;
   out_230881002087446555[140] = 0.0;
   out_230881002087446555[141] = 0.0;
   out_230881002087446555[142] = 0.0;
   out_230881002087446555[143] = 0.0;
   out_230881002087446555[144] = 0.0;
   out_230881002087446555[145] = 0.0;
   out_230881002087446555[146] = 0.0;
   out_230881002087446555[147] = 0.0;
   out_230881002087446555[148] = 0.0;
   out_230881002087446555[149] = 0.0;
   out_230881002087446555[150] = 0.0;
   out_230881002087446555[151] = 0.0;
   out_230881002087446555[152] = 1.0;
   out_230881002087446555[153] = 0.0;
   out_230881002087446555[154] = 0.0;
   out_230881002087446555[155] = 0.0;
   out_230881002087446555[156] = 0.0;
   out_230881002087446555[157] = 0.0;
   out_230881002087446555[158] = 0.0;
   out_230881002087446555[159] = 0.0;
   out_230881002087446555[160] = 0.0;
   out_230881002087446555[161] = 0.0;
   out_230881002087446555[162] = 0.0;
   out_230881002087446555[163] = 0.0;
   out_230881002087446555[164] = 0.0;
   out_230881002087446555[165] = 0.0;
   out_230881002087446555[166] = 0.0;
   out_230881002087446555[167] = 0.0;
   out_230881002087446555[168] = 0.0;
   out_230881002087446555[169] = 0.0;
   out_230881002087446555[170] = 0.0;
   out_230881002087446555[171] = 1.0;
   out_230881002087446555[172] = 0.0;
   out_230881002087446555[173] = 0.0;
   out_230881002087446555[174] = 0.0;
   out_230881002087446555[175] = 0.0;
   out_230881002087446555[176] = 0.0;
   out_230881002087446555[177] = 0.0;
   out_230881002087446555[178] = 0.0;
   out_230881002087446555[179] = 0.0;
   out_230881002087446555[180] = 0.0;
   out_230881002087446555[181] = 0.0;
   out_230881002087446555[182] = 0.0;
   out_230881002087446555[183] = 0.0;
   out_230881002087446555[184] = 0.0;
   out_230881002087446555[185] = 0.0;
   out_230881002087446555[186] = 0.0;
   out_230881002087446555[187] = 0.0;
   out_230881002087446555[188] = 0.0;
   out_230881002087446555[189] = 0.0;
   out_230881002087446555[190] = 1.0;
   out_230881002087446555[191] = 0.0;
   out_230881002087446555[192] = 0.0;
   out_230881002087446555[193] = 0.0;
   out_230881002087446555[194] = 0.0;
   out_230881002087446555[195] = 0.0;
   out_230881002087446555[196] = 0.0;
   out_230881002087446555[197] = 0.0;
   out_230881002087446555[198] = 0.0;
   out_230881002087446555[199] = 0.0;
   out_230881002087446555[200] = 0.0;
   out_230881002087446555[201] = 0.0;
   out_230881002087446555[202] = 0.0;
   out_230881002087446555[203] = 0.0;
   out_230881002087446555[204] = 0.0;
   out_230881002087446555[205] = 0.0;
   out_230881002087446555[206] = 0.0;
   out_230881002087446555[207] = 0.0;
   out_230881002087446555[208] = 0.0;
   out_230881002087446555[209] = 1.0;
   out_230881002087446555[210] = 0.0;
   out_230881002087446555[211] = 0.0;
   out_230881002087446555[212] = 0.0;
   out_230881002087446555[213] = 0.0;
   out_230881002087446555[214] = 0.0;
   out_230881002087446555[215] = 0.0;
   out_230881002087446555[216] = 0.0;
   out_230881002087446555[217] = 0.0;
   out_230881002087446555[218] = 0.0;
   out_230881002087446555[219] = 0.0;
   out_230881002087446555[220] = 0.0;
   out_230881002087446555[221] = 0.0;
   out_230881002087446555[222] = 0.0;
   out_230881002087446555[223] = 0.0;
   out_230881002087446555[224] = 0.0;
   out_230881002087446555[225] = 0.0;
   out_230881002087446555[226] = 0.0;
   out_230881002087446555[227] = 0.0;
   out_230881002087446555[228] = 1.0;
   out_230881002087446555[229] = 0.0;
   out_230881002087446555[230] = 0.0;
   out_230881002087446555[231] = 0.0;
   out_230881002087446555[232] = 0.0;
   out_230881002087446555[233] = 0.0;
   out_230881002087446555[234] = 0.0;
   out_230881002087446555[235] = 0.0;
   out_230881002087446555[236] = 0.0;
   out_230881002087446555[237] = 0.0;
   out_230881002087446555[238] = 0.0;
   out_230881002087446555[239] = 0.0;
   out_230881002087446555[240] = 0.0;
   out_230881002087446555[241] = 0.0;
   out_230881002087446555[242] = 0.0;
   out_230881002087446555[243] = 0.0;
   out_230881002087446555[244] = 0.0;
   out_230881002087446555[245] = 0.0;
   out_230881002087446555[246] = 0.0;
   out_230881002087446555[247] = 1.0;
   out_230881002087446555[248] = 0.0;
   out_230881002087446555[249] = 0.0;
   out_230881002087446555[250] = 0.0;
   out_230881002087446555[251] = 0.0;
   out_230881002087446555[252] = 0.0;
   out_230881002087446555[253] = 0.0;
   out_230881002087446555[254] = 0.0;
   out_230881002087446555[255] = 0.0;
   out_230881002087446555[256] = 0.0;
   out_230881002087446555[257] = 0.0;
   out_230881002087446555[258] = 0.0;
   out_230881002087446555[259] = 0.0;
   out_230881002087446555[260] = 0.0;
   out_230881002087446555[261] = 0.0;
   out_230881002087446555[262] = 0.0;
   out_230881002087446555[263] = 0.0;
   out_230881002087446555[264] = 0.0;
   out_230881002087446555[265] = 0.0;
   out_230881002087446555[266] = 1.0;
   out_230881002087446555[267] = 0.0;
   out_230881002087446555[268] = 0.0;
   out_230881002087446555[269] = 0.0;
   out_230881002087446555[270] = 0.0;
   out_230881002087446555[271] = 0.0;
   out_230881002087446555[272] = 0.0;
   out_230881002087446555[273] = 0.0;
   out_230881002087446555[274] = 0.0;
   out_230881002087446555[275] = 0.0;
   out_230881002087446555[276] = 0.0;
   out_230881002087446555[277] = 0.0;
   out_230881002087446555[278] = 0.0;
   out_230881002087446555[279] = 0.0;
   out_230881002087446555[280] = 0.0;
   out_230881002087446555[281] = 0.0;
   out_230881002087446555[282] = 0.0;
   out_230881002087446555[283] = 0.0;
   out_230881002087446555[284] = 0.0;
   out_230881002087446555[285] = 1.0;
   out_230881002087446555[286] = 0.0;
   out_230881002087446555[287] = 0.0;
   out_230881002087446555[288] = 0.0;
   out_230881002087446555[289] = 0.0;
   out_230881002087446555[290] = 0.0;
   out_230881002087446555[291] = 0.0;
   out_230881002087446555[292] = 0.0;
   out_230881002087446555[293] = 0.0;
   out_230881002087446555[294] = 0.0;
   out_230881002087446555[295] = 0.0;
   out_230881002087446555[296] = 0.0;
   out_230881002087446555[297] = 0.0;
   out_230881002087446555[298] = 0.0;
   out_230881002087446555[299] = 0.0;
   out_230881002087446555[300] = 0.0;
   out_230881002087446555[301] = 0.0;
   out_230881002087446555[302] = 0.0;
   out_230881002087446555[303] = 0.0;
   out_230881002087446555[304] = 1.0;
   out_230881002087446555[305] = 0.0;
   out_230881002087446555[306] = 0.0;
   out_230881002087446555[307] = 0.0;
   out_230881002087446555[308] = 0.0;
   out_230881002087446555[309] = 0.0;
   out_230881002087446555[310] = 0.0;
   out_230881002087446555[311] = 0.0;
   out_230881002087446555[312] = 0.0;
   out_230881002087446555[313] = 0.0;
   out_230881002087446555[314] = 0.0;
   out_230881002087446555[315] = 0.0;
   out_230881002087446555[316] = 0.0;
   out_230881002087446555[317] = 0.0;
   out_230881002087446555[318] = 0.0;
   out_230881002087446555[319] = 0.0;
   out_230881002087446555[320] = 0.0;
   out_230881002087446555[321] = 0.0;
   out_230881002087446555[322] = 0.0;
   out_230881002087446555[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_7515598229942337125) {
   out_7515598229942337125[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_7515598229942337125[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_7515598229942337125[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_7515598229942337125[3] = dt*state[12] + state[3];
   out_7515598229942337125[4] = dt*state[13] + state[4];
   out_7515598229942337125[5] = dt*state[14] + state[5];
   out_7515598229942337125[6] = state[6];
   out_7515598229942337125[7] = state[7];
   out_7515598229942337125[8] = state[8];
   out_7515598229942337125[9] = state[9];
   out_7515598229942337125[10] = state[10];
   out_7515598229942337125[11] = state[11];
   out_7515598229942337125[12] = state[12];
   out_7515598229942337125[13] = state[13];
   out_7515598229942337125[14] = state[14];
   out_7515598229942337125[15] = state[15];
   out_7515598229942337125[16] = state[16];
   out_7515598229942337125[17] = state[17];
}
void F_fun(double *state, double dt, double *out_1734808733268298500) {
   out_1734808733268298500[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_1734808733268298500[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_1734808733268298500[2] = 0;
   out_1734808733268298500[3] = 0;
   out_1734808733268298500[4] = 0;
   out_1734808733268298500[5] = 0;
   out_1734808733268298500[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_1734808733268298500[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_1734808733268298500[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_1734808733268298500[9] = 0;
   out_1734808733268298500[10] = 0;
   out_1734808733268298500[11] = 0;
   out_1734808733268298500[12] = 0;
   out_1734808733268298500[13] = 0;
   out_1734808733268298500[14] = 0;
   out_1734808733268298500[15] = 0;
   out_1734808733268298500[16] = 0;
   out_1734808733268298500[17] = 0;
   out_1734808733268298500[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_1734808733268298500[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_1734808733268298500[20] = 0;
   out_1734808733268298500[21] = 0;
   out_1734808733268298500[22] = 0;
   out_1734808733268298500[23] = 0;
   out_1734808733268298500[24] = 0;
   out_1734808733268298500[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_1734808733268298500[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_1734808733268298500[27] = 0;
   out_1734808733268298500[28] = 0;
   out_1734808733268298500[29] = 0;
   out_1734808733268298500[30] = 0;
   out_1734808733268298500[31] = 0;
   out_1734808733268298500[32] = 0;
   out_1734808733268298500[33] = 0;
   out_1734808733268298500[34] = 0;
   out_1734808733268298500[35] = 0;
   out_1734808733268298500[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_1734808733268298500[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_1734808733268298500[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_1734808733268298500[39] = 0;
   out_1734808733268298500[40] = 0;
   out_1734808733268298500[41] = 0;
   out_1734808733268298500[42] = 0;
   out_1734808733268298500[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_1734808733268298500[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_1734808733268298500[45] = 0;
   out_1734808733268298500[46] = 0;
   out_1734808733268298500[47] = 0;
   out_1734808733268298500[48] = 0;
   out_1734808733268298500[49] = 0;
   out_1734808733268298500[50] = 0;
   out_1734808733268298500[51] = 0;
   out_1734808733268298500[52] = 0;
   out_1734808733268298500[53] = 0;
   out_1734808733268298500[54] = 0;
   out_1734808733268298500[55] = 0;
   out_1734808733268298500[56] = 0;
   out_1734808733268298500[57] = 1;
   out_1734808733268298500[58] = 0;
   out_1734808733268298500[59] = 0;
   out_1734808733268298500[60] = 0;
   out_1734808733268298500[61] = 0;
   out_1734808733268298500[62] = 0;
   out_1734808733268298500[63] = 0;
   out_1734808733268298500[64] = 0;
   out_1734808733268298500[65] = 0;
   out_1734808733268298500[66] = dt;
   out_1734808733268298500[67] = 0;
   out_1734808733268298500[68] = 0;
   out_1734808733268298500[69] = 0;
   out_1734808733268298500[70] = 0;
   out_1734808733268298500[71] = 0;
   out_1734808733268298500[72] = 0;
   out_1734808733268298500[73] = 0;
   out_1734808733268298500[74] = 0;
   out_1734808733268298500[75] = 0;
   out_1734808733268298500[76] = 1;
   out_1734808733268298500[77] = 0;
   out_1734808733268298500[78] = 0;
   out_1734808733268298500[79] = 0;
   out_1734808733268298500[80] = 0;
   out_1734808733268298500[81] = 0;
   out_1734808733268298500[82] = 0;
   out_1734808733268298500[83] = 0;
   out_1734808733268298500[84] = 0;
   out_1734808733268298500[85] = dt;
   out_1734808733268298500[86] = 0;
   out_1734808733268298500[87] = 0;
   out_1734808733268298500[88] = 0;
   out_1734808733268298500[89] = 0;
   out_1734808733268298500[90] = 0;
   out_1734808733268298500[91] = 0;
   out_1734808733268298500[92] = 0;
   out_1734808733268298500[93] = 0;
   out_1734808733268298500[94] = 0;
   out_1734808733268298500[95] = 1;
   out_1734808733268298500[96] = 0;
   out_1734808733268298500[97] = 0;
   out_1734808733268298500[98] = 0;
   out_1734808733268298500[99] = 0;
   out_1734808733268298500[100] = 0;
   out_1734808733268298500[101] = 0;
   out_1734808733268298500[102] = 0;
   out_1734808733268298500[103] = 0;
   out_1734808733268298500[104] = dt;
   out_1734808733268298500[105] = 0;
   out_1734808733268298500[106] = 0;
   out_1734808733268298500[107] = 0;
   out_1734808733268298500[108] = 0;
   out_1734808733268298500[109] = 0;
   out_1734808733268298500[110] = 0;
   out_1734808733268298500[111] = 0;
   out_1734808733268298500[112] = 0;
   out_1734808733268298500[113] = 0;
   out_1734808733268298500[114] = 1;
   out_1734808733268298500[115] = 0;
   out_1734808733268298500[116] = 0;
   out_1734808733268298500[117] = 0;
   out_1734808733268298500[118] = 0;
   out_1734808733268298500[119] = 0;
   out_1734808733268298500[120] = 0;
   out_1734808733268298500[121] = 0;
   out_1734808733268298500[122] = 0;
   out_1734808733268298500[123] = 0;
   out_1734808733268298500[124] = 0;
   out_1734808733268298500[125] = 0;
   out_1734808733268298500[126] = 0;
   out_1734808733268298500[127] = 0;
   out_1734808733268298500[128] = 0;
   out_1734808733268298500[129] = 0;
   out_1734808733268298500[130] = 0;
   out_1734808733268298500[131] = 0;
   out_1734808733268298500[132] = 0;
   out_1734808733268298500[133] = 1;
   out_1734808733268298500[134] = 0;
   out_1734808733268298500[135] = 0;
   out_1734808733268298500[136] = 0;
   out_1734808733268298500[137] = 0;
   out_1734808733268298500[138] = 0;
   out_1734808733268298500[139] = 0;
   out_1734808733268298500[140] = 0;
   out_1734808733268298500[141] = 0;
   out_1734808733268298500[142] = 0;
   out_1734808733268298500[143] = 0;
   out_1734808733268298500[144] = 0;
   out_1734808733268298500[145] = 0;
   out_1734808733268298500[146] = 0;
   out_1734808733268298500[147] = 0;
   out_1734808733268298500[148] = 0;
   out_1734808733268298500[149] = 0;
   out_1734808733268298500[150] = 0;
   out_1734808733268298500[151] = 0;
   out_1734808733268298500[152] = 1;
   out_1734808733268298500[153] = 0;
   out_1734808733268298500[154] = 0;
   out_1734808733268298500[155] = 0;
   out_1734808733268298500[156] = 0;
   out_1734808733268298500[157] = 0;
   out_1734808733268298500[158] = 0;
   out_1734808733268298500[159] = 0;
   out_1734808733268298500[160] = 0;
   out_1734808733268298500[161] = 0;
   out_1734808733268298500[162] = 0;
   out_1734808733268298500[163] = 0;
   out_1734808733268298500[164] = 0;
   out_1734808733268298500[165] = 0;
   out_1734808733268298500[166] = 0;
   out_1734808733268298500[167] = 0;
   out_1734808733268298500[168] = 0;
   out_1734808733268298500[169] = 0;
   out_1734808733268298500[170] = 0;
   out_1734808733268298500[171] = 1;
   out_1734808733268298500[172] = 0;
   out_1734808733268298500[173] = 0;
   out_1734808733268298500[174] = 0;
   out_1734808733268298500[175] = 0;
   out_1734808733268298500[176] = 0;
   out_1734808733268298500[177] = 0;
   out_1734808733268298500[178] = 0;
   out_1734808733268298500[179] = 0;
   out_1734808733268298500[180] = 0;
   out_1734808733268298500[181] = 0;
   out_1734808733268298500[182] = 0;
   out_1734808733268298500[183] = 0;
   out_1734808733268298500[184] = 0;
   out_1734808733268298500[185] = 0;
   out_1734808733268298500[186] = 0;
   out_1734808733268298500[187] = 0;
   out_1734808733268298500[188] = 0;
   out_1734808733268298500[189] = 0;
   out_1734808733268298500[190] = 1;
   out_1734808733268298500[191] = 0;
   out_1734808733268298500[192] = 0;
   out_1734808733268298500[193] = 0;
   out_1734808733268298500[194] = 0;
   out_1734808733268298500[195] = 0;
   out_1734808733268298500[196] = 0;
   out_1734808733268298500[197] = 0;
   out_1734808733268298500[198] = 0;
   out_1734808733268298500[199] = 0;
   out_1734808733268298500[200] = 0;
   out_1734808733268298500[201] = 0;
   out_1734808733268298500[202] = 0;
   out_1734808733268298500[203] = 0;
   out_1734808733268298500[204] = 0;
   out_1734808733268298500[205] = 0;
   out_1734808733268298500[206] = 0;
   out_1734808733268298500[207] = 0;
   out_1734808733268298500[208] = 0;
   out_1734808733268298500[209] = 1;
   out_1734808733268298500[210] = 0;
   out_1734808733268298500[211] = 0;
   out_1734808733268298500[212] = 0;
   out_1734808733268298500[213] = 0;
   out_1734808733268298500[214] = 0;
   out_1734808733268298500[215] = 0;
   out_1734808733268298500[216] = 0;
   out_1734808733268298500[217] = 0;
   out_1734808733268298500[218] = 0;
   out_1734808733268298500[219] = 0;
   out_1734808733268298500[220] = 0;
   out_1734808733268298500[221] = 0;
   out_1734808733268298500[222] = 0;
   out_1734808733268298500[223] = 0;
   out_1734808733268298500[224] = 0;
   out_1734808733268298500[225] = 0;
   out_1734808733268298500[226] = 0;
   out_1734808733268298500[227] = 0;
   out_1734808733268298500[228] = 1;
   out_1734808733268298500[229] = 0;
   out_1734808733268298500[230] = 0;
   out_1734808733268298500[231] = 0;
   out_1734808733268298500[232] = 0;
   out_1734808733268298500[233] = 0;
   out_1734808733268298500[234] = 0;
   out_1734808733268298500[235] = 0;
   out_1734808733268298500[236] = 0;
   out_1734808733268298500[237] = 0;
   out_1734808733268298500[238] = 0;
   out_1734808733268298500[239] = 0;
   out_1734808733268298500[240] = 0;
   out_1734808733268298500[241] = 0;
   out_1734808733268298500[242] = 0;
   out_1734808733268298500[243] = 0;
   out_1734808733268298500[244] = 0;
   out_1734808733268298500[245] = 0;
   out_1734808733268298500[246] = 0;
   out_1734808733268298500[247] = 1;
   out_1734808733268298500[248] = 0;
   out_1734808733268298500[249] = 0;
   out_1734808733268298500[250] = 0;
   out_1734808733268298500[251] = 0;
   out_1734808733268298500[252] = 0;
   out_1734808733268298500[253] = 0;
   out_1734808733268298500[254] = 0;
   out_1734808733268298500[255] = 0;
   out_1734808733268298500[256] = 0;
   out_1734808733268298500[257] = 0;
   out_1734808733268298500[258] = 0;
   out_1734808733268298500[259] = 0;
   out_1734808733268298500[260] = 0;
   out_1734808733268298500[261] = 0;
   out_1734808733268298500[262] = 0;
   out_1734808733268298500[263] = 0;
   out_1734808733268298500[264] = 0;
   out_1734808733268298500[265] = 0;
   out_1734808733268298500[266] = 1;
   out_1734808733268298500[267] = 0;
   out_1734808733268298500[268] = 0;
   out_1734808733268298500[269] = 0;
   out_1734808733268298500[270] = 0;
   out_1734808733268298500[271] = 0;
   out_1734808733268298500[272] = 0;
   out_1734808733268298500[273] = 0;
   out_1734808733268298500[274] = 0;
   out_1734808733268298500[275] = 0;
   out_1734808733268298500[276] = 0;
   out_1734808733268298500[277] = 0;
   out_1734808733268298500[278] = 0;
   out_1734808733268298500[279] = 0;
   out_1734808733268298500[280] = 0;
   out_1734808733268298500[281] = 0;
   out_1734808733268298500[282] = 0;
   out_1734808733268298500[283] = 0;
   out_1734808733268298500[284] = 0;
   out_1734808733268298500[285] = 1;
   out_1734808733268298500[286] = 0;
   out_1734808733268298500[287] = 0;
   out_1734808733268298500[288] = 0;
   out_1734808733268298500[289] = 0;
   out_1734808733268298500[290] = 0;
   out_1734808733268298500[291] = 0;
   out_1734808733268298500[292] = 0;
   out_1734808733268298500[293] = 0;
   out_1734808733268298500[294] = 0;
   out_1734808733268298500[295] = 0;
   out_1734808733268298500[296] = 0;
   out_1734808733268298500[297] = 0;
   out_1734808733268298500[298] = 0;
   out_1734808733268298500[299] = 0;
   out_1734808733268298500[300] = 0;
   out_1734808733268298500[301] = 0;
   out_1734808733268298500[302] = 0;
   out_1734808733268298500[303] = 0;
   out_1734808733268298500[304] = 1;
   out_1734808733268298500[305] = 0;
   out_1734808733268298500[306] = 0;
   out_1734808733268298500[307] = 0;
   out_1734808733268298500[308] = 0;
   out_1734808733268298500[309] = 0;
   out_1734808733268298500[310] = 0;
   out_1734808733268298500[311] = 0;
   out_1734808733268298500[312] = 0;
   out_1734808733268298500[313] = 0;
   out_1734808733268298500[314] = 0;
   out_1734808733268298500[315] = 0;
   out_1734808733268298500[316] = 0;
   out_1734808733268298500[317] = 0;
   out_1734808733268298500[318] = 0;
   out_1734808733268298500[319] = 0;
   out_1734808733268298500[320] = 0;
   out_1734808733268298500[321] = 0;
   out_1734808733268298500[322] = 0;
   out_1734808733268298500[323] = 1;
}
void h_4(double *state, double *unused, double *out_5738748106133999168) {
   out_5738748106133999168[0] = state[6] + state[9];
   out_5738748106133999168[1] = state[7] + state[10];
   out_5738748106133999168[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_4002688211931354127) {
   out_4002688211931354127[0] = 0;
   out_4002688211931354127[1] = 0;
   out_4002688211931354127[2] = 0;
   out_4002688211931354127[3] = 0;
   out_4002688211931354127[4] = 0;
   out_4002688211931354127[5] = 0;
   out_4002688211931354127[6] = 1;
   out_4002688211931354127[7] = 0;
   out_4002688211931354127[8] = 0;
   out_4002688211931354127[9] = 1;
   out_4002688211931354127[10] = 0;
   out_4002688211931354127[11] = 0;
   out_4002688211931354127[12] = 0;
   out_4002688211931354127[13] = 0;
   out_4002688211931354127[14] = 0;
   out_4002688211931354127[15] = 0;
   out_4002688211931354127[16] = 0;
   out_4002688211931354127[17] = 0;
   out_4002688211931354127[18] = 0;
   out_4002688211931354127[19] = 0;
   out_4002688211931354127[20] = 0;
   out_4002688211931354127[21] = 0;
   out_4002688211931354127[22] = 0;
   out_4002688211931354127[23] = 0;
   out_4002688211931354127[24] = 0;
   out_4002688211931354127[25] = 1;
   out_4002688211931354127[26] = 0;
   out_4002688211931354127[27] = 0;
   out_4002688211931354127[28] = 1;
   out_4002688211931354127[29] = 0;
   out_4002688211931354127[30] = 0;
   out_4002688211931354127[31] = 0;
   out_4002688211931354127[32] = 0;
   out_4002688211931354127[33] = 0;
   out_4002688211931354127[34] = 0;
   out_4002688211931354127[35] = 0;
   out_4002688211931354127[36] = 0;
   out_4002688211931354127[37] = 0;
   out_4002688211931354127[38] = 0;
   out_4002688211931354127[39] = 0;
   out_4002688211931354127[40] = 0;
   out_4002688211931354127[41] = 0;
   out_4002688211931354127[42] = 0;
   out_4002688211931354127[43] = 0;
   out_4002688211931354127[44] = 1;
   out_4002688211931354127[45] = 0;
   out_4002688211931354127[46] = 0;
   out_4002688211931354127[47] = 1;
   out_4002688211931354127[48] = 0;
   out_4002688211931354127[49] = 0;
   out_4002688211931354127[50] = 0;
   out_4002688211931354127[51] = 0;
   out_4002688211931354127[52] = 0;
   out_4002688211931354127[53] = 0;
}
void h_10(double *state, double *unused, double *out_5469958614434535899) {
   out_5469958614434535899[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_5469958614434535899[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_5469958614434535899[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_6327455986419743559) {
   out_6327455986419743559[0] = 0;
   out_6327455986419743559[1] = 9.8100000000000005*cos(state[1]);
   out_6327455986419743559[2] = 0;
   out_6327455986419743559[3] = 0;
   out_6327455986419743559[4] = -state[8];
   out_6327455986419743559[5] = state[7];
   out_6327455986419743559[6] = 0;
   out_6327455986419743559[7] = state[5];
   out_6327455986419743559[8] = -state[4];
   out_6327455986419743559[9] = 0;
   out_6327455986419743559[10] = 0;
   out_6327455986419743559[11] = 0;
   out_6327455986419743559[12] = 1;
   out_6327455986419743559[13] = 0;
   out_6327455986419743559[14] = 0;
   out_6327455986419743559[15] = 1;
   out_6327455986419743559[16] = 0;
   out_6327455986419743559[17] = 0;
   out_6327455986419743559[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_6327455986419743559[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_6327455986419743559[20] = 0;
   out_6327455986419743559[21] = state[8];
   out_6327455986419743559[22] = 0;
   out_6327455986419743559[23] = -state[6];
   out_6327455986419743559[24] = -state[5];
   out_6327455986419743559[25] = 0;
   out_6327455986419743559[26] = state[3];
   out_6327455986419743559[27] = 0;
   out_6327455986419743559[28] = 0;
   out_6327455986419743559[29] = 0;
   out_6327455986419743559[30] = 0;
   out_6327455986419743559[31] = 1;
   out_6327455986419743559[32] = 0;
   out_6327455986419743559[33] = 0;
   out_6327455986419743559[34] = 1;
   out_6327455986419743559[35] = 0;
   out_6327455986419743559[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_6327455986419743559[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_6327455986419743559[38] = 0;
   out_6327455986419743559[39] = -state[7];
   out_6327455986419743559[40] = state[6];
   out_6327455986419743559[41] = 0;
   out_6327455986419743559[42] = state[4];
   out_6327455986419743559[43] = -state[3];
   out_6327455986419743559[44] = 0;
   out_6327455986419743559[45] = 0;
   out_6327455986419743559[46] = 0;
   out_6327455986419743559[47] = 0;
   out_6327455986419743559[48] = 0;
   out_6327455986419743559[49] = 0;
   out_6327455986419743559[50] = 1;
   out_6327455986419743559[51] = 0;
   out_6327455986419743559[52] = 0;
   out_6327455986419743559[53] = 1;
}
void h_13(double *state, double *unused, double *out_4757981965902022494) {
   out_4757981965902022494[0] = state[3];
   out_4757981965902022494[1] = state[4];
   out_4757981965902022494[2] = state[5];
}
void H_13(double *state, double *unused, double *out_7214962037263686928) {
   out_7214962037263686928[0] = 0;
   out_7214962037263686928[1] = 0;
   out_7214962037263686928[2] = 0;
   out_7214962037263686928[3] = 1;
   out_7214962037263686928[4] = 0;
   out_7214962037263686928[5] = 0;
   out_7214962037263686928[6] = 0;
   out_7214962037263686928[7] = 0;
   out_7214962037263686928[8] = 0;
   out_7214962037263686928[9] = 0;
   out_7214962037263686928[10] = 0;
   out_7214962037263686928[11] = 0;
   out_7214962037263686928[12] = 0;
   out_7214962037263686928[13] = 0;
   out_7214962037263686928[14] = 0;
   out_7214962037263686928[15] = 0;
   out_7214962037263686928[16] = 0;
   out_7214962037263686928[17] = 0;
   out_7214962037263686928[18] = 0;
   out_7214962037263686928[19] = 0;
   out_7214962037263686928[20] = 0;
   out_7214962037263686928[21] = 0;
   out_7214962037263686928[22] = 1;
   out_7214962037263686928[23] = 0;
   out_7214962037263686928[24] = 0;
   out_7214962037263686928[25] = 0;
   out_7214962037263686928[26] = 0;
   out_7214962037263686928[27] = 0;
   out_7214962037263686928[28] = 0;
   out_7214962037263686928[29] = 0;
   out_7214962037263686928[30] = 0;
   out_7214962037263686928[31] = 0;
   out_7214962037263686928[32] = 0;
   out_7214962037263686928[33] = 0;
   out_7214962037263686928[34] = 0;
   out_7214962037263686928[35] = 0;
   out_7214962037263686928[36] = 0;
   out_7214962037263686928[37] = 0;
   out_7214962037263686928[38] = 0;
   out_7214962037263686928[39] = 0;
   out_7214962037263686928[40] = 0;
   out_7214962037263686928[41] = 1;
   out_7214962037263686928[42] = 0;
   out_7214962037263686928[43] = 0;
   out_7214962037263686928[44] = 0;
   out_7214962037263686928[45] = 0;
   out_7214962037263686928[46] = 0;
   out_7214962037263686928[47] = 0;
   out_7214962037263686928[48] = 0;
   out_7214962037263686928[49] = 0;
   out_7214962037263686928[50] = 0;
   out_7214962037263686928[51] = 0;
   out_7214962037263686928[52] = 0;
   out_7214962037263686928[53] = 0;
}
void h_14(double *state, double *unused, double *out_6416907027380241315) {
   out_6416907027380241315[0] = state[6];
   out_6416907027380241315[1] = state[7];
   out_6416907027380241315[2] = state[8];
}
void H_14(double *state, double *unused, double *out_919899779635981831) {
   out_919899779635981831[0] = 0;
   out_919899779635981831[1] = 0;
   out_919899779635981831[2] = 0;
   out_919899779635981831[3] = 0;
   out_919899779635981831[4] = 0;
   out_919899779635981831[5] = 0;
   out_919899779635981831[6] = 1;
   out_919899779635981831[7] = 0;
   out_919899779635981831[8] = 0;
   out_919899779635981831[9] = 0;
   out_919899779635981831[10] = 0;
   out_919899779635981831[11] = 0;
   out_919899779635981831[12] = 0;
   out_919899779635981831[13] = 0;
   out_919899779635981831[14] = 0;
   out_919899779635981831[15] = 0;
   out_919899779635981831[16] = 0;
   out_919899779635981831[17] = 0;
   out_919899779635981831[18] = 0;
   out_919899779635981831[19] = 0;
   out_919899779635981831[20] = 0;
   out_919899779635981831[21] = 0;
   out_919899779635981831[22] = 0;
   out_919899779635981831[23] = 0;
   out_919899779635981831[24] = 0;
   out_919899779635981831[25] = 1;
   out_919899779635981831[26] = 0;
   out_919899779635981831[27] = 0;
   out_919899779635981831[28] = 0;
   out_919899779635981831[29] = 0;
   out_919899779635981831[30] = 0;
   out_919899779635981831[31] = 0;
   out_919899779635981831[32] = 0;
   out_919899779635981831[33] = 0;
   out_919899779635981831[34] = 0;
   out_919899779635981831[35] = 0;
   out_919899779635981831[36] = 0;
   out_919899779635981831[37] = 0;
   out_919899779635981831[38] = 0;
   out_919899779635981831[39] = 0;
   out_919899779635981831[40] = 0;
   out_919899779635981831[41] = 0;
   out_919899779635981831[42] = 0;
   out_919899779635981831[43] = 0;
   out_919899779635981831[44] = 1;
   out_919899779635981831[45] = 0;
   out_919899779635981831[46] = 0;
   out_919899779635981831[47] = 0;
   out_919899779635981831[48] = 0;
   out_919899779635981831[49] = 0;
   out_919899779635981831[50] = 0;
   out_919899779635981831[51] = 0;
   out_919899779635981831[52] = 0;
   out_919899779635981831[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_8954543502953545600) {
  err_fun(nom_x, delta_x, out_8954543502953545600);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_4429120357540117455) {
  inv_err_fun(nom_x, true_x, out_4429120357540117455);
}
void pose_H_mod_fun(double *state, double *out_230881002087446555) {
  H_mod_fun(state, out_230881002087446555);
}
void pose_f_fun(double *state, double dt, double *out_7515598229942337125) {
  f_fun(state,  dt, out_7515598229942337125);
}
void pose_F_fun(double *state, double dt, double *out_1734808733268298500) {
  F_fun(state,  dt, out_1734808733268298500);
}
void pose_h_4(double *state, double *unused, double *out_5738748106133999168) {
  h_4(state, unused, out_5738748106133999168);
}
void pose_H_4(double *state, double *unused, double *out_4002688211931354127) {
  H_4(state, unused, out_4002688211931354127);
}
void pose_h_10(double *state, double *unused, double *out_5469958614434535899) {
  h_10(state, unused, out_5469958614434535899);
}
void pose_H_10(double *state, double *unused, double *out_6327455986419743559) {
  H_10(state, unused, out_6327455986419743559);
}
void pose_h_13(double *state, double *unused, double *out_4757981965902022494) {
  h_13(state, unused, out_4757981965902022494);
}
void pose_H_13(double *state, double *unused, double *out_7214962037263686928) {
  H_13(state, unused, out_7214962037263686928);
}
void pose_h_14(double *state, double *unused, double *out_6416907027380241315) {
  h_14(state, unused, out_6416907027380241315);
}
void pose_H_14(double *state, double *unused, double *out_919899779635981831) {
  H_14(state, unused, out_919899779635981831);
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
