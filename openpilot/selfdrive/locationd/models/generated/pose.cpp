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
void err_fun(double *nom_x, double *delta_x, double *out_6163145922104175593) {
   out_6163145922104175593[0] = delta_x[0] + nom_x[0];
   out_6163145922104175593[1] = delta_x[1] + nom_x[1];
   out_6163145922104175593[2] = delta_x[2] + nom_x[2];
   out_6163145922104175593[3] = delta_x[3] + nom_x[3];
   out_6163145922104175593[4] = delta_x[4] + nom_x[4];
   out_6163145922104175593[5] = delta_x[5] + nom_x[5];
   out_6163145922104175593[6] = delta_x[6] + nom_x[6];
   out_6163145922104175593[7] = delta_x[7] + nom_x[7];
   out_6163145922104175593[8] = delta_x[8] + nom_x[8];
   out_6163145922104175593[9] = delta_x[9] + nom_x[9];
   out_6163145922104175593[10] = delta_x[10] + nom_x[10];
   out_6163145922104175593[11] = delta_x[11] + nom_x[11];
   out_6163145922104175593[12] = delta_x[12] + nom_x[12];
   out_6163145922104175593[13] = delta_x[13] + nom_x[13];
   out_6163145922104175593[14] = delta_x[14] + nom_x[14];
   out_6163145922104175593[15] = delta_x[15] + nom_x[15];
   out_6163145922104175593[16] = delta_x[16] + nom_x[16];
   out_6163145922104175593[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_2416579067635792744) {
   out_2416579067635792744[0] = -nom_x[0] + true_x[0];
   out_2416579067635792744[1] = -nom_x[1] + true_x[1];
   out_2416579067635792744[2] = -nom_x[2] + true_x[2];
   out_2416579067635792744[3] = -nom_x[3] + true_x[3];
   out_2416579067635792744[4] = -nom_x[4] + true_x[4];
   out_2416579067635792744[5] = -nom_x[5] + true_x[5];
   out_2416579067635792744[6] = -nom_x[6] + true_x[6];
   out_2416579067635792744[7] = -nom_x[7] + true_x[7];
   out_2416579067635792744[8] = -nom_x[8] + true_x[8];
   out_2416579067635792744[9] = -nom_x[9] + true_x[9];
   out_2416579067635792744[10] = -nom_x[10] + true_x[10];
   out_2416579067635792744[11] = -nom_x[11] + true_x[11];
   out_2416579067635792744[12] = -nom_x[12] + true_x[12];
   out_2416579067635792744[13] = -nom_x[13] + true_x[13];
   out_2416579067635792744[14] = -nom_x[14] + true_x[14];
   out_2416579067635792744[15] = -nom_x[15] + true_x[15];
   out_2416579067635792744[16] = -nom_x[16] + true_x[16];
   out_2416579067635792744[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_3962135837270256316) {
   out_3962135837270256316[0] = 1.0;
   out_3962135837270256316[1] = 0.0;
   out_3962135837270256316[2] = 0.0;
   out_3962135837270256316[3] = 0.0;
   out_3962135837270256316[4] = 0.0;
   out_3962135837270256316[5] = 0.0;
   out_3962135837270256316[6] = 0.0;
   out_3962135837270256316[7] = 0.0;
   out_3962135837270256316[8] = 0.0;
   out_3962135837270256316[9] = 0.0;
   out_3962135837270256316[10] = 0.0;
   out_3962135837270256316[11] = 0.0;
   out_3962135837270256316[12] = 0.0;
   out_3962135837270256316[13] = 0.0;
   out_3962135837270256316[14] = 0.0;
   out_3962135837270256316[15] = 0.0;
   out_3962135837270256316[16] = 0.0;
   out_3962135837270256316[17] = 0.0;
   out_3962135837270256316[18] = 0.0;
   out_3962135837270256316[19] = 1.0;
   out_3962135837270256316[20] = 0.0;
   out_3962135837270256316[21] = 0.0;
   out_3962135837270256316[22] = 0.0;
   out_3962135837270256316[23] = 0.0;
   out_3962135837270256316[24] = 0.0;
   out_3962135837270256316[25] = 0.0;
   out_3962135837270256316[26] = 0.0;
   out_3962135837270256316[27] = 0.0;
   out_3962135837270256316[28] = 0.0;
   out_3962135837270256316[29] = 0.0;
   out_3962135837270256316[30] = 0.0;
   out_3962135837270256316[31] = 0.0;
   out_3962135837270256316[32] = 0.0;
   out_3962135837270256316[33] = 0.0;
   out_3962135837270256316[34] = 0.0;
   out_3962135837270256316[35] = 0.0;
   out_3962135837270256316[36] = 0.0;
   out_3962135837270256316[37] = 0.0;
   out_3962135837270256316[38] = 1.0;
   out_3962135837270256316[39] = 0.0;
   out_3962135837270256316[40] = 0.0;
   out_3962135837270256316[41] = 0.0;
   out_3962135837270256316[42] = 0.0;
   out_3962135837270256316[43] = 0.0;
   out_3962135837270256316[44] = 0.0;
   out_3962135837270256316[45] = 0.0;
   out_3962135837270256316[46] = 0.0;
   out_3962135837270256316[47] = 0.0;
   out_3962135837270256316[48] = 0.0;
   out_3962135837270256316[49] = 0.0;
   out_3962135837270256316[50] = 0.0;
   out_3962135837270256316[51] = 0.0;
   out_3962135837270256316[52] = 0.0;
   out_3962135837270256316[53] = 0.0;
   out_3962135837270256316[54] = 0.0;
   out_3962135837270256316[55] = 0.0;
   out_3962135837270256316[56] = 0.0;
   out_3962135837270256316[57] = 1.0;
   out_3962135837270256316[58] = 0.0;
   out_3962135837270256316[59] = 0.0;
   out_3962135837270256316[60] = 0.0;
   out_3962135837270256316[61] = 0.0;
   out_3962135837270256316[62] = 0.0;
   out_3962135837270256316[63] = 0.0;
   out_3962135837270256316[64] = 0.0;
   out_3962135837270256316[65] = 0.0;
   out_3962135837270256316[66] = 0.0;
   out_3962135837270256316[67] = 0.0;
   out_3962135837270256316[68] = 0.0;
   out_3962135837270256316[69] = 0.0;
   out_3962135837270256316[70] = 0.0;
   out_3962135837270256316[71] = 0.0;
   out_3962135837270256316[72] = 0.0;
   out_3962135837270256316[73] = 0.0;
   out_3962135837270256316[74] = 0.0;
   out_3962135837270256316[75] = 0.0;
   out_3962135837270256316[76] = 1.0;
   out_3962135837270256316[77] = 0.0;
   out_3962135837270256316[78] = 0.0;
   out_3962135837270256316[79] = 0.0;
   out_3962135837270256316[80] = 0.0;
   out_3962135837270256316[81] = 0.0;
   out_3962135837270256316[82] = 0.0;
   out_3962135837270256316[83] = 0.0;
   out_3962135837270256316[84] = 0.0;
   out_3962135837270256316[85] = 0.0;
   out_3962135837270256316[86] = 0.0;
   out_3962135837270256316[87] = 0.0;
   out_3962135837270256316[88] = 0.0;
   out_3962135837270256316[89] = 0.0;
   out_3962135837270256316[90] = 0.0;
   out_3962135837270256316[91] = 0.0;
   out_3962135837270256316[92] = 0.0;
   out_3962135837270256316[93] = 0.0;
   out_3962135837270256316[94] = 0.0;
   out_3962135837270256316[95] = 1.0;
   out_3962135837270256316[96] = 0.0;
   out_3962135837270256316[97] = 0.0;
   out_3962135837270256316[98] = 0.0;
   out_3962135837270256316[99] = 0.0;
   out_3962135837270256316[100] = 0.0;
   out_3962135837270256316[101] = 0.0;
   out_3962135837270256316[102] = 0.0;
   out_3962135837270256316[103] = 0.0;
   out_3962135837270256316[104] = 0.0;
   out_3962135837270256316[105] = 0.0;
   out_3962135837270256316[106] = 0.0;
   out_3962135837270256316[107] = 0.0;
   out_3962135837270256316[108] = 0.0;
   out_3962135837270256316[109] = 0.0;
   out_3962135837270256316[110] = 0.0;
   out_3962135837270256316[111] = 0.0;
   out_3962135837270256316[112] = 0.0;
   out_3962135837270256316[113] = 0.0;
   out_3962135837270256316[114] = 1.0;
   out_3962135837270256316[115] = 0.0;
   out_3962135837270256316[116] = 0.0;
   out_3962135837270256316[117] = 0.0;
   out_3962135837270256316[118] = 0.0;
   out_3962135837270256316[119] = 0.0;
   out_3962135837270256316[120] = 0.0;
   out_3962135837270256316[121] = 0.0;
   out_3962135837270256316[122] = 0.0;
   out_3962135837270256316[123] = 0.0;
   out_3962135837270256316[124] = 0.0;
   out_3962135837270256316[125] = 0.0;
   out_3962135837270256316[126] = 0.0;
   out_3962135837270256316[127] = 0.0;
   out_3962135837270256316[128] = 0.0;
   out_3962135837270256316[129] = 0.0;
   out_3962135837270256316[130] = 0.0;
   out_3962135837270256316[131] = 0.0;
   out_3962135837270256316[132] = 0.0;
   out_3962135837270256316[133] = 1.0;
   out_3962135837270256316[134] = 0.0;
   out_3962135837270256316[135] = 0.0;
   out_3962135837270256316[136] = 0.0;
   out_3962135837270256316[137] = 0.0;
   out_3962135837270256316[138] = 0.0;
   out_3962135837270256316[139] = 0.0;
   out_3962135837270256316[140] = 0.0;
   out_3962135837270256316[141] = 0.0;
   out_3962135837270256316[142] = 0.0;
   out_3962135837270256316[143] = 0.0;
   out_3962135837270256316[144] = 0.0;
   out_3962135837270256316[145] = 0.0;
   out_3962135837270256316[146] = 0.0;
   out_3962135837270256316[147] = 0.0;
   out_3962135837270256316[148] = 0.0;
   out_3962135837270256316[149] = 0.0;
   out_3962135837270256316[150] = 0.0;
   out_3962135837270256316[151] = 0.0;
   out_3962135837270256316[152] = 1.0;
   out_3962135837270256316[153] = 0.0;
   out_3962135837270256316[154] = 0.0;
   out_3962135837270256316[155] = 0.0;
   out_3962135837270256316[156] = 0.0;
   out_3962135837270256316[157] = 0.0;
   out_3962135837270256316[158] = 0.0;
   out_3962135837270256316[159] = 0.0;
   out_3962135837270256316[160] = 0.0;
   out_3962135837270256316[161] = 0.0;
   out_3962135837270256316[162] = 0.0;
   out_3962135837270256316[163] = 0.0;
   out_3962135837270256316[164] = 0.0;
   out_3962135837270256316[165] = 0.0;
   out_3962135837270256316[166] = 0.0;
   out_3962135837270256316[167] = 0.0;
   out_3962135837270256316[168] = 0.0;
   out_3962135837270256316[169] = 0.0;
   out_3962135837270256316[170] = 0.0;
   out_3962135837270256316[171] = 1.0;
   out_3962135837270256316[172] = 0.0;
   out_3962135837270256316[173] = 0.0;
   out_3962135837270256316[174] = 0.0;
   out_3962135837270256316[175] = 0.0;
   out_3962135837270256316[176] = 0.0;
   out_3962135837270256316[177] = 0.0;
   out_3962135837270256316[178] = 0.0;
   out_3962135837270256316[179] = 0.0;
   out_3962135837270256316[180] = 0.0;
   out_3962135837270256316[181] = 0.0;
   out_3962135837270256316[182] = 0.0;
   out_3962135837270256316[183] = 0.0;
   out_3962135837270256316[184] = 0.0;
   out_3962135837270256316[185] = 0.0;
   out_3962135837270256316[186] = 0.0;
   out_3962135837270256316[187] = 0.0;
   out_3962135837270256316[188] = 0.0;
   out_3962135837270256316[189] = 0.0;
   out_3962135837270256316[190] = 1.0;
   out_3962135837270256316[191] = 0.0;
   out_3962135837270256316[192] = 0.0;
   out_3962135837270256316[193] = 0.0;
   out_3962135837270256316[194] = 0.0;
   out_3962135837270256316[195] = 0.0;
   out_3962135837270256316[196] = 0.0;
   out_3962135837270256316[197] = 0.0;
   out_3962135837270256316[198] = 0.0;
   out_3962135837270256316[199] = 0.0;
   out_3962135837270256316[200] = 0.0;
   out_3962135837270256316[201] = 0.0;
   out_3962135837270256316[202] = 0.0;
   out_3962135837270256316[203] = 0.0;
   out_3962135837270256316[204] = 0.0;
   out_3962135837270256316[205] = 0.0;
   out_3962135837270256316[206] = 0.0;
   out_3962135837270256316[207] = 0.0;
   out_3962135837270256316[208] = 0.0;
   out_3962135837270256316[209] = 1.0;
   out_3962135837270256316[210] = 0.0;
   out_3962135837270256316[211] = 0.0;
   out_3962135837270256316[212] = 0.0;
   out_3962135837270256316[213] = 0.0;
   out_3962135837270256316[214] = 0.0;
   out_3962135837270256316[215] = 0.0;
   out_3962135837270256316[216] = 0.0;
   out_3962135837270256316[217] = 0.0;
   out_3962135837270256316[218] = 0.0;
   out_3962135837270256316[219] = 0.0;
   out_3962135837270256316[220] = 0.0;
   out_3962135837270256316[221] = 0.0;
   out_3962135837270256316[222] = 0.0;
   out_3962135837270256316[223] = 0.0;
   out_3962135837270256316[224] = 0.0;
   out_3962135837270256316[225] = 0.0;
   out_3962135837270256316[226] = 0.0;
   out_3962135837270256316[227] = 0.0;
   out_3962135837270256316[228] = 1.0;
   out_3962135837270256316[229] = 0.0;
   out_3962135837270256316[230] = 0.0;
   out_3962135837270256316[231] = 0.0;
   out_3962135837270256316[232] = 0.0;
   out_3962135837270256316[233] = 0.0;
   out_3962135837270256316[234] = 0.0;
   out_3962135837270256316[235] = 0.0;
   out_3962135837270256316[236] = 0.0;
   out_3962135837270256316[237] = 0.0;
   out_3962135837270256316[238] = 0.0;
   out_3962135837270256316[239] = 0.0;
   out_3962135837270256316[240] = 0.0;
   out_3962135837270256316[241] = 0.0;
   out_3962135837270256316[242] = 0.0;
   out_3962135837270256316[243] = 0.0;
   out_3962135837270256316[244] = 0.0;
   out_3962135837270256316[245] = 0.0;
   out_3962135837270256316[246] = 0.0;
   out_3962135837270256316[247] = 1.0;
   out_3962135837270256316[248] = 0.0;
   out_3962135837270256316[249] = 0.0;
   out_3962135837270256316[250] = 0.0;
   out_3962135837270256316[251] = 0.0;
   out_3962135837270256316[252] = 0.0;
   out_3962135837270256316[253] = 0.0;
   out_3962135837270256316[254] = 0.0;
   out_3962135837270256316[255] = 0.0;
   out_3962135837270256316[256] = 0.0;
   out_3962135837270256316[257] = 0.0;
   out_3962135837270256316[258] = 0.0;
   out_3962135837270256316[259] = 0.0;
   out_3962135837270256316[260] = 0.0;
   out_3962135837270256316[261] = 0.0;
   out_3962135837270256316[262] = 0.0;
   out_3962135837270256316[263] = 0.0;
   out_3962135837270256316[264] = 0.0;
   out_3962135837270256316[265] = 0.0;
   out_3962135837270256316[266] = 1.0;
   out_3962135837270256316[267] = 0.0;
   out_3962135837270256316[268] = 0.0;
   out_3962135837270256316[269] = 0.0;
   out_3962135837270256316[270] = 0.0;
   out_3962135837270256316[271] = 0.0;
   out_3962135837270256316[272] = 0.0;
   out_3962135837270256316[273] = 0.0;
   out_3962135837270256316[274] = 0.0;
   out_3962135837270256316[275] = 0.0;
   out_3962135837270256316[276] = 0.0;
   out_3962135837270256316[277] = 0.0;
   out_3962135837270256316[278] = 0.0;
   out_3962135837270256316[279] = 0.0;
   out_3962135837270256316[280] = 0.0;
   out_3962135837270256316[281] = 0.0;
   out_3962135837270256316[282] = 0.0;
   out_3962135837270256316[283] = 0.0;
   out_3962135837270256316[284] = 0.0;
   out_3962135837270256316[285] = 1.0;
   out_3962135837270256316[286] = 0.0;
   out_3962135837270256316[287] = 0.0;
   out_3962135837270256316[288] = 0.0;
   out_3962135837270256316[289] = 0.0;
   out_3962135837270256316[290] = 0.0;
   out_3962135837270256316[291] = 0.0;
   out_3962135837270256316[292] = 0.0;
   out_3962135837270256316[293] = 0.0;
   out_3962135837270256316[294] = 0.0;
   out_3962135837270256316[295] = 0.0;
   out_3962135837270256316[296] = 0.0;
   out_3962135837270256316[297] = 0.0;
   out_3962135837270256316[298] = 0.0;
   out_3962135837270256316[299] = 0.0;
   out_3962135837270256316[300] = 0.0;
   out_3962135837270256316[301] = 0.0;
   out_3962135837270256316[302] = 0.0;
   out_3962135837270256316[303] = 0.0;
   out_3962135837270256316[304] = 1.0;
   out_3962135837270256316[305] = 0.0;
   out_3962135837270256316[306] = 0.0;
   out_3962135837270256316[307] = 0.0;
   out_3962135837270256316[308] = 0.0;
   out_3962135837270256316[309] = 0.0;
   out_3962135837270256316[310] = 0.0;
   out_3962135837270256316[311] = 0.0;
   out_3962135837270256316[312] = 0.0;
   out_3962135837270256316[313] = 0.0;
   out_3962135837270256316[314] = 0.0;
   out_3962135837270256316[315] = 0.0;
   out_3962135837270256316[316] = 0.0;
   out_3962135837270256316[317] = 0.0;
   out_3962135837270256316[318] = 0.0;
   out_3962135837270256316[319] = 0.0;
   out_3962135837270256316[320] = 0.0;
   out_3962135837270256316[321] = 0.0;
   out_3962135837270256316[322] = 0.0;
   out_3962135837270256316[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_6578666550680470474) {
   out_6578666550680470474[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_6578666550680470474[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_6578666550680470474[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_6578666550680470474[3] = dt*state[12] + state[3];
   out_6578666550680470474[4] = dt*state[13] + state[4];
   out_6578666550680470474[5] = dt*state[14] + state[5];
   out_6578666550680470474[6] = state[6];
   out_6578666550680470474[7] = state[7];
   out_6578666550680470474[8] = state[8];
   out_6578666550680470474[9] = state[9];
   out_6578666550680470474[10] = state[10];
   out_6578666550680470474[11] = state[11];
   out_6578666550680470474[12] = state[12];
   out_6578666550680470474[13] = state[13];
   out_6578666550680470474[14] = state[14];
   out_6578666550680470474[15] = state[15];
   out_6578666550680470474[16] = state[16];
   out_6578666550680470474[17] = state[17];
}
void F_fun(double *state, double dt, double *out_3360432821028871183) {
   out_3360432821028871183[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3360432821028871183[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3360432821028871183[2] = 0;
   out_3360432821028871183[3] = 0;
   out_3360432821028871183[4] = 0;
   out_3360432821028871183[5] = 0;
   out_3360432821028871183[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3360432821028871183[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3360432821028871183[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3360432821028871183[9] = 0;
   out_3360432821028871183[10] = 0;
   out_3360432821028871183[11] = 0;
   out_3360432821028871183[12] = 0;
   out_3360432821028871183[13] = 0;
   out_3360432821028871183[14] = 0;
   out_3360432821028871183[15] = 0;
   out_3360432821028871183[16] = 0;
   out_3360432821028871183[17] = 0;
   out_3360432821028871183[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3360432821028871183[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3360432821028871183[20] = 0;
   out_3360432821028871183[21] = 0;
   out_3360432821028871183[22] = 0;
   out_3360432821028871183[23] = 0;
   out_3360432821028871183[24] = 0;
   out_3360432821028871183[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3360432821028871183[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3360432821028871183[27] = 0;
   out_3360432821028871183[28] = 0;
   out_3360432821028871183[29] = 0;
   out_3360432821028871183[30] = 0;
   out_3360432821028871183[31] = 0;
   out_3360432821028871183[32] = 0;
   out_3360432821028871183[33] = 0;
   out_3360432821028871183[34] = 0;
   out_3360432821028871183[35] = 0;
   out_3360432821028871183[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3360432821028871183[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3360432821028871183[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3360432821028871183[39] = 0;
   out_3360432821028871183[40] = 0;
   out_3360432821028871183[41] = 0;
   out_3360432821028871183[42] = 0;
   out_3360432821028871183[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3360432821028871183[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3360432821028871183[45] = 0;
   out_3360432821028871183[46] = 0;
   out_3360432821028871183[47] = 0;
   out_3360432821028871183[48] = 0;
   out_3360432821028871183[49] = 0;
   out_3360432821028871183[50] = 0;
   out_3360432821028871183[51] = 0;
   out_3360432821028871183[52] = 0;
   out_3360432821028871183[53] = 0;
   out_3360432821028871183[54] = 0;
   out_3360432821028871183[55] = 0;
   out_3360432821028871183[56] = 0;
   out_3360432821028871183[57] = 1;
   out_3360432821028871183[58] = 0;
   out_3360432821028871183[59] = 0;
   out_3360432821028871183[60] = 0;
   out_3360432821028871183[61] = 0;
   out_3360432821028871183[62] = 0;
   out_3360432821028871183[63] = 0;
   out_3360432821028871183[64] = 0;
   out_3360432821028871183[65] = 0;
   out_3360432821028871183[66] = dt;
   out_3360432821028871183[67] = 0;
   out_3360432821028871183[68] = 0;
   out_3360432821028871183[69] = 0;
   out_3360432821028871183[70] = 0;
   out_3360432821028871183[71] = 0;
   out_3360432821028871183[72] = 0;
   out_3360432821028871183[73] = 0;
   out_3360432821028871183[74] = 0;
   out_3360432821028871183[75] = 0;
   out_3360432821028871183[76] = 1;
   out_3360432821028871183[77] = 0;
   out_3360432821028871183[78] = 0;
   out_3360432821028871183[79] = 0;
   out_3360432821028871183[80] = 0;
   out_3360432821028871183[81] = 0;
   out_3360432821028871183[82] = 0;
   out_3360432821028871183[83] = 0;
   out_3360432821028871183[84] = 0;
   out_3360432821028871183[85] = dt;
   out_3360432821028871183[86] = 0;
   out_3360432821028871183[87] = 0;
   out_3360432821028871183[88] = 0;
   out_3360432821028871183[89] = 0;
   out_3360432821028871183[90] = 0;
   out_3360432821028871183[91] = 0;
   out_3360432821028871183[92] = 0;
   out_3360432821028871183[93] = 0;
   out_3360432821028871183[94] = 0;
   out_3360432821028871183[95] = 1;
   out_3360432821028871183[96] = 0;
   out_3360432821028871183[97] = 0;
   out_3360432821028871183[98] = 0;
   out_3360432821028871183[99] = 0;
   out_3360432821028871183[100] = 0;
   out_3360432821028871183[101] = 0;
   out_3360432821028871183[102] = 0;
   out_3360432821028871183[103] = 0;
   out_3360432821028871183[104] = dt;
   out_3360432821028871183[105] = 0;
   out_3360432821028871183[106] = 0;
   out_3360432821028871183[107] = 0;
   out_3360432821028871183[108] = 0;
   out_3360432821028871183[109] = 0;
   out_3360432821028871183[110] = 0;
   out_3360432821028871183[111] = 0;
   out_3360432821028871183[112] = 0;
   out_3360432821028871183[113] = 0;
   out_3360432821028871183[114] = 1;
   out_3360432821028871183[115] = 0;
   out_3360432821028871183[116] = 0;
   out_3360432821028871183[117] = 0;
   out_3360432821028871183[118] = 0;
   out_3360432821028871183[119] = 0;
   out_3360432821028871183[120] = 0;
   out_3360432821028871183[121] = 0;
   out_3360432821028871183[122] = 0;
   out_3360432821028871183[123] = 0;
   out_3360432821028871183[124] = 0;
   out_3360432821028871183[125] = 0;
   out_3360432821028871183[126] = 0;
   out_3360432821028871183[127] = 0;
   out_3360432821028871183[128] = 0;
   out_3360432821028871183[129] = 0;
   out_3360432821028871183[130] = 0;
   out_3360432821028871183[131] = 0;
   out_3360432821028871183[132] = 0;
   out_3360432821028871183[133] = 1;
   out_3360432821028871183[134] = 0;
   out_3360432821028871183[135] = 0;
   out_3360432821028871183[136] = 0;
   out_3360432821028871183[137] = 0;
   out_3360432821028871183[138] = 0;
   out_3360432821028871183[139] = 0;
   out_3360432821028871183[140] = 0;
   out_3360432821028871183[141] = 0;
   out_3360432821028871183[142] = 0;
   out_3360432821028871183[143] = 0;
   out_3360432821028871183[144] = 0;
   out_3360432821028871183[145] = 0;
   out_3360432821028871183[146] = 0;
   out_3360432821028871183[147] = 0;
   out_3360432821028871183[148] = 0;
   out_3360432821028871183[149] = 0;
   out_3360432821028871183[150] = 0;
   out_3360432821028871183[151] = 0;
   out_3360432821028871183[152] = 1;
   out_3360432821028871183[153] = 0;
   out_3360432821028871183[154] = 0;
   out_3360432821028871183[155] = 0;
   out_3360432821028871183[156] = 0;
   out_3360432821028871183[157] = 0;
   out_3360432821028871183[158] = 0;
   out_3360432821028871183[159] = 0;
   out_3360432821028871183[160] = 0;
   out_3360432821028871183[161] = 0;
   out_3360432821028871183[162] = 0;
   out_3360432821028871183[163] = 0;
   out_3360432821028871183[164] = 0;
   out_3360432821028871183[165] = 0;
   out_3360432821028871183[166] = 0;
   out_3360432821028871183[167] = 0;
   out_3360432821028871183[168] = 0;
   out_3360432821028871183[169] = 0;
   out_3360432821028871183[170] = 0;
   out_3360432821028871183[171] = 1;
   out_3360432821028871183[172] = 0;
   out_3360432821028871183[173] = 0;
   out_3360432821028871183[174] = 0;
   out_3360432821028871183[175] = 0;
   out_3360432821028871183[176] = 0;
   out_3360432821028871183[177] = 0;
   out_3360432821028871183[178] = 0;
   out_3360432821028871183[179] = 0;
   out_3360432821028871183[180] = 0;
   out_3360432821028871183[181] = 0;
   out_3360432821028871183[182] = 0;
   out_3360432821028871183[183] = 0;
   out_3360432821028871183[184] = 0;
   out_3360432821028871183[185] = 0;
   out_3360432821028871183[186] = 0;
   out_3360432821028871183[187] = 0;
   out_3360432821028871183[188] = 0;
   out_3360432821028871183[189] = 0;
   out_3360432821028871183[190] = 1;
   out_3360432821028871183[191] = 0;
   out_3360432821028871183[192] = 0;
   out_3360432821028871183[193] = 0;
   out_3360432821028871183[194] = 0;
   out_3360432821028871183[195] = 0;
   out_3360432821028871183[196] = 0;
   out_3360432821028871183[197] = 0;
   out_3360432821028871183[198] = 0;
   out_3360432821028871183[199] = 0;
   out_3360432821028871183[200] = 0;
   out_3360432821028871183[201] = 0;
   out_3360432821028871183[202] = 0;
   out_3360432821028871183[203] = 0;
   out_3360432821028871183[204] = 0;
   out_3360432821028871183[205] = 0;
   out_3360432821028871183[206] = 0;
   out_3360432821028871183[207] = 0;
   out_3360432821028871183[208] = 0;
   out_3360432821028871183[209] = 1;
   out_3360432821028871183[210] = 0;
   out_3360432821028871183[211] = 0;
   out_3360432821028871183[212] = 0;
   out_3360432821028871183[213] = 0;
   out_3360432821028871183[214] = 0;
   out_3360432821028871183[215] = 0;
   out_3360432821028871183[216] = 0;
   out_3360432821028871183[217] = 0;
   out_3360432821028871183[218] = 0;
   out_3360432821028871183[219] = 0;
   out_3360432821028871183[220] = 0;
   out_3360432821028871183[221] = 0;
   out_3360432821028871183[222] = 0;
   out_3360432821028871183[223] = 0;
   out_3360432821028871183[224] = 0;
   out_3360432821028871183[225] = 0;
   out_3360432821028871183[226] = 0;
   out_3360432821028871183[227] = 0;
   out_3360432821028871183[228] = 1;
   out_3360432821028871183[229] = 0;
   out_3360432821028871183[230] = 0;
   out_3360432821028871183[231] = 0;
   out_3360432821028871183[232] = 0;
   out_3360432821028871183[233] = 0;
   out_3360432821028871183[234] = 0;
   out_3360432821028871183[235] = 0;
   out_3360432821028871183[236] = 0;
   out_3360432821028871183[237] = 0;
   out_3360432821028871183[238] = 0;
   out_3360432821028871183[239] = 0;
   out_3360432821028871183[240] = 0;
   out_3360432821028871183[241] = 0;
   out_3360432821028871183[242] = 0;
   out_3360432821028871183[243] = 0;
   out_3360432821028871183[244] = 0;
   out_3360432821028871183[245] = 0;
   out_3360432821028871183[246] = 0;
   out_3360432821028871183[247] = 1;
   out_3360432821028871183[248] = 0;
   out_3360432821028871183[249] = 0;
   out_3360432821028871183[250] = 0;
   out_3360432821028871183[251] = 0;
   out_3360432821028871183[252] = 0;
   out_3360432821028871183[253] = 0;
   out_3360432821028871183[254] = 0;
   out_3360432821028871183[255] = 0;
   out_3360432821028871183[256] = 0;
   out_3360432821028871183[257] = 0;
   out_3360432821028871183[258] = 0;
   out_3360432821028871183[259] = 0;
   out_3360432821028871183[260] = 0;
   out_3360432821028871183[261] = 0;
   out_3360432821028871183[262] = 0;
   out_3360432821028871183[263] = 0;
   out_3360432821028871183[264] = 0;
   out_3360432821028871183[265] = 0;
   out_3360432821028871183[266] = 1;
   out_3360432821028871183[267] = 0;
   out_3360432821028871183[268] = 0;
   out_3360432821028871183[269] = 0;
   out_3360432821028871183[270] = 0;
   out_3360432821028871183[271] = 0;
   out_3360432821028871183[272] = 0;
   out_3360432821028871183[273] = 0;
   out_3360432821028871183[274] = 0;
   out_3360432821028871183[275] = 0;
   out_3360432821028871183[276] = 0;
   out_3360432821028871183[277] = 0;
   out_3360432821028871183[278] = 0;
   out_3360432821028871183[279] = 0;
   out_3360432821028871183[280] = 0;
   out_3360432821028871183[281] = 0;
   out_3360432821028871183[282] = 0;
   out_3360432821028871183[283] = 0;
   out_3360432821028871183[284] = 0;
   out_3360432821028871183[285] = 1;
   out_3360432821028871183[286] = 0;
   out_3360432821028871183[287] = 0;
   out_3360432821028871183[288] = 0;
   out_3360432821028871183[289] = 0;
   out_3360432821028871183[290] = 0;
   out_3360432821028871183[291] = 0;
   out_3360432821028871183[292] = 0;
   out_3360432821028871183[293] = 0;
   out_3360432821028871183[294] = 0;
   out_3360432821028871183[295] = 0;
   out_3360432821028871183[296] = 0;
   out_3360432821028871183[297] = 0;
   out_3360432821028871183[298] = 0;
   out_3360432821028871183[299] = 0;
   out_3360432821028871183[300] = 0;
   out_3360432821028871183[301] = 0;
   out_3360432821028871183[302] = 0;
   out_3360432821028871183[303] = 0;
   out_3360432821028871183[304] = 1;
   out_3360432821028871183[305] = 0;
   out_3360432821028871183[306] = 0;
   out_3360432821028871183[307] = 0;
   out_3360432821028871183[308] = 0;
   out_3360432821028871183[309] = 0;
   out_3360432821028871183[310] = 0;
   out_3360432821028871183[311] = 0;
   out_3360432821028871183[312] = 0;
   out_3360432821028871183[313] = 0;
   out_3360432821028871183[314] = 0;
   out_3360432821028871183[315] = 0;
   out_3360432821028871183[316] = 0;
   out_3360432821028871183[317] = 0;
   out_3360432821028871183[318] = 0;
   out_3360432821028871183[319] = 0;
   out_3360432821028871183[320] = 0;
   out_3360432821028871183[321] = 0;
   out_3360432821028871183[322] = 0;
   out_3360432821028871183[323] = 1;
}
void h_4(double *state, double *unused, double *out_6216561684044621445) {
   out_6216561684044621445[0] = state[6] + state[9];
   out_6216561684044621445[1] = state[7] + state[10];
   out_6216561684044621445[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_6284303352466070533) {
   out_6284303352466070533[0] = 0;
   out_6284303352466070533[1] = 0;
   out_6284303352466070533[2] = 0;
   out_6284303352466070533[3] = 0;
   out_6284303352466070533[4] = 0;
   out_6284303352466070533[5] = 0;
   out_6284303352466070533[6] = 1;
   out_6284303352466070533[7] = 0;
   out_6284303352466070533[8] = 0;
   out_6284303352466070533[9] = 1;
   out_6284303352466070533[10] = 0;
   out_6284303352466070533[11] = 0;
   out_6284303352466070533[12] = 0;
   out_6284303352466070533[13] = 0;
   out_6284303352466070533[14] = 0;
   out_6284303352466070533[15] = 0;
   out_6284303352466070533[16] = 0;
   out_6284303352466070533[17] = 0;
   out_6284303352466070533[18] = 0;
   out_6284303352466070533[19] = 0;
   out_6284303352466070533[20] = 0;
   out_6284303352466070533[21] = 0;
   out_6284303352466070533[22] = 0;
   out_6284303352466070533[23] = 0;
   out_6284303352466070533[24] = 0;
   out_6284303352466070533[25] = 1;
   out_6284303352466070533[26] = 0;
   out_6284303352466070533[27] = 0;
   out_6284303352466070533[28] = 1;
   out_6284303352466070533[29] = 0;
   out_6284303352466070533[30] = 0;
   out_6284303352466070533[31] = 0;
   out_6284303352466070533[32] = 0;
   out_6284303352466070533[33] = 0;
   out_6284303352466070533[34] = 0;
   out_6284303352466070533[35] = 0;
   out_6284303352466070533[36] = 0;
   out_6284303352466070533[37] = 0;
   out_6284303352466070533[38] = 0;
   out_6284303352466070533[39] = 0;
   out_6284303352466070533[40] = 0;
   out_6284303352466070533[41] = 0;
   out_6284303352466070533[42] = 0;
   out_6284303352466070533[43] = 0;
   out_6284303352466070533[44] = 1;
   out_6284303352466070533[45] = 0;
   out_6284303352466070533[46] = 0;
   out_6284303352466070533[47] = 1;
   out_6284303352466070533[48] = 0;
   out_6284303352466070533[49] = 0;
   out_6284303352466070533[50] = 0;
   out_6284303352466070533[51] = 0;
   out_6284303352466070533[52] = 0;
   out_6284303352466070533[53] = 0;
}
void h_10(double *state, double *unused, double *out_8921172237656055896) {
   out_8921172237656055896[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_8921172237656055896[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_8921172237656055896[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_4166178305681923609) {
   out_4166178305681923609[0] = 0;
   out_4166178305681923609[1] = 9.8100000000000005*cos(state[1]);
   out_4166178305681923609[2] = 0;
   out_4166178305681923609[3] = 0;
   out_4166178305681923609[4] = -state[8];
   out_4166178305681923609[5] = state[7];
   out_4166178305681923609[6] = 0;
   out_4166178305681923609[7] = state[5];
   out_4166178305681923609[8] = -state[4];
   out_4166178305681923609[9] = 0;
   out_4166178305681923609[10] = 0;
   out_4166178305681923609[11] = 0;
   out_4166178305681923609[12] = 1;
   out_4166178305681923609[13] = 0;
   out_4166178305681923609[14] = 0;
   out_4166178305681923609[15] = 1;
   out_4166178305681923609[16] = 0;
   out_4166178305681923609[17] = 0;
   out_4166178305681923609[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_4166178305681923609[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_4166178305681923609[20] = 0;
   out_4166178305681923609[21] = state[8];
   out_4166178305681923609[22] = 0;
   out_4166178305681923609[23] = -state[6];
   out_4166178305681923609[24] = -state[5];
   out_4166178305681923609[25] = 0;
   out_4166178305681923609[26] = state[3];
   out_4166178305681923609[27] = 0;
   out_4166178305681923609[28] = 0;
   out_4166178305681923609[29] = 0;
   out_4166178305681923609[30] = 0;
   out_4166178305681923609[31] = 1;
   out_4166178305681923609[32] = 0;
   out_4166178305681923609[33] = 0;
   out_4166178305681923609[34] = 1;
   out_4166178305681923609[35] = 0;
   out_4166178305681923609[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_4166178305681923609[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_4166178305681923609[38] = 0;
   out_4166178305681923609[39] = -state[7];
   out_4166178305681923609[40] = state[6];
   out_4166178305681923609[41] = 0;
   out_4166178305681923609[42] = state[4];
   out_4166178305681923609[43] = -state[3];
   out_4166178305681923609[44] = 0;
   out_4166178305681923609[45] = 0;
   out_4166178305681923609[46] = 0;
   out_4166178305681923609[47] = 0;
   out_4166178305681923609[48] = 0;
   out_4166178305681923609[49] = 0;
   out_4166178305681923609[50] = 1;
   out_4166178305681923609[51] = 0;
   out_4166178305681923609[52] = 0;
   out_4166178305681923609[53] = 1;
}
void h_13(double *state, double *unused, double *out_4225136367746162929) {
   out_4225136367746162929[0] = state[3];
   out_4225136367746162929[1] = state[4];
   out_4225136367746162929[2] = state[5];
}
void H_13(double *state, double *unused, double *out_1326327855850630396) {
   out_1326327855850630396[0] = 0;
   out_1326327855850630396[1] = 0;
   out_1326327855850630396[2] = 0;
   out_1326327855850630396[3] = 1;
   out_1326327855850630396[4] = 0;
   out_1326327855850630396[5] = 0;
   out_1326327855850630396[6] = 0;
   out_1326327855850630396[7] = 0;
   out_1326327855850630396[8] = 0;
   out_1326327855850630396[9] = 0;
   out_1326327855850630396[10] = 0;
   out_1326327855850630396[11] = 0;
   out_1326327855850630396[12] = 0;
   out_1326327855850630396[13] = 0;
   out_1326327855850630396[14] = 0;
   out_1326327855850630396[15] = 0;
   out_1326327855850630396[16] = 0;
   out_1326327855850630396[17] = 0;
   out_1326327855850630396[18] = 0;
   out_1326327855850630396[19] = 0;
   out_1326327855850630396[20] = 0;
   out_1326327855850630396[21] = 0;
   out_1326327855850630396[22] = 1;
   out_1326327855850630396[23] = 0;
   out_1326327855850630396[24] = 0;
   out_1326327855850630396[25] = 0;
   out_1326327855850630396[26] = 0;
   out_1326327855850630396[27] = 0;
   out_1326327855850630396[28] = 0;
   out_1326327855850630396[29] = 0;
   out_1326327855850630396[30] = 0;
   out_1326327855850630396[31] = 0;
   out_1326327855850630396[32] = 0;
   out_1326327855850630396[33] = 0;
   out_1326327855850630396[34] = 0;
   out_1326327855850630396[35] = 0;
   out_1326327855850630396[36] = 0;
   out_1326327855850630396[37] = 0;
   out_1326327855850630396[38] = 0;
   out_1326327855850630396[39] = 0;
   out_1326327855850630396[40] = 0;
   out_1326327855850630396[41] = 1;
   out_1326327855850630396[42] = 0;
   out_1326327855850630396[43] = 0;
   out_1326327855850630396[44] = 0;
   out_1326327855850630396[45] = 0;
   out_1326327855850630396[46] = 0;
   out_1326327855850630396[47] = 0;
   out_1326327855850630396[48] = 0;
   out_1326327855850630396[49] = 0;
   out_1326327855850630396[50] = 0;
   out_1326327855850630396[51] = 0;
   out_1326327855850630396[52] = 0;
   out_1326327855850630396[53] = 0;
}
void h_14(double *state, double *unused, double *out_3049593094819758450) {
   out_3049593094819758450[0] = state[6];
   out_3049593094819758450[1] = state[7];
   out_3049593094819758450[2] = state[8];
}
void H_14(double *state, double *unused, double *out_2321062496126586004) {
   out_2321062496126586004[0] = 0;
   out_2321062496126586004[1] = 0;
   out_2321062496126586004[2] = 0;
   out_2321062496126586004[3] = 0;
   out_2321062496126586004[4] = 0;
   out_2321062496126586004[5] = 0;
   out_2321062496126586004[6] = 1;
   out_2321062496126586004[7] = 0;
   out_2321062496126586004[8] = 0;
   out_2321062496126586004[9] = 0;
   out_2321062496126586004[10] = 0;
   out_2321062496126586004[11] = 0;
   out_2321062496126586004[12] = 0;
   out_2321062496126586004[13] = 0;
   out_2321062496126586004[14] = 0;
   out_2321062496126586004[15] = 0;
   out_2321062496126586004[16] = 0;
   out_2321062496126586004[17] = 0;
   out_2321062496126586004[18] = 0;
   out_2321062496126586004[19] = 0;
   out_2321062496126586004[20] = 0;
   out_2321062496126586004[21] = 0;
   out_2321062496126586004[22] = 0;
   out_2321062496126586004[23] = 0;
   out_2321062496126586004[24] = 0;
   out_2321062496126586004[25] = 1;
   out_2321062496126586004[26] = 0;
   out_2321062496126586004[27] = 0;
   out_2321062496126586004[28] = 0;
   out_2321062496126586004[29] = 0;
   out_2321062496126586004[30] = 0;
   out_2321062496126586004[31] = 0;
   out_2321062496126586004[32] = 0;
   out_2321062496126586004[33] = 0;
   out_2321062496126586004[34] = 0;
   out_2321062496126586004[35] = 0;
   out_2321062496126586004[36] = 0;
   out_2321062496126586004[37] = 0;
   out_2321062496126586004[38] = 0;
   out_2321062496126586004[39] = 0;
   out_2321062496126586004[40] = 0;
   out_2321062496126586004[41] = 0;
   out_2321062496126586004[42] = 0;
   out_2321062496126586004[43] = 0;
   out_2321062496126586004[44] = 1;
   out_2321062496126586004[45] = 0;
   out_2321062496126586004[46] = 0;
   out_2321062496126586004[47] = 0;
   out_2321062496126586004[48] = 0;
   out_2321062496126586004[49] = 0;
   out_2321062496126586004[50] = 0;
   out_2321062496126586004[51] = 0;
   out_2321062496126586004[52] = 0;
   out_2321062496126586004[53] = 0;
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
void pose_err_fun(double *nom_x, double *delta_x, double *out_6163145922104175593) {
  err_fun(nom_x, delta_x, out_6163145922104175593);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_2416579067635792744) {
  inv_err_fun(nom_x, true_x, out_2416579067635792744);
}
void pose_H_mod_fun(double *state, double *out_3962135837270256316) {
  H_mod_fun(state, out_3962135837270256316);
}
void pose_f_fun(double *state, double dt, double *out_6578666550680470474) {
  f_fun(state,  dt, out_6578666550680470474);
}
void pose_F_fun(double *state, double dt, double *out_3360432821028871183) {
  F_fun(state,  dt, out_3360432821028871183);
}
void pose_h_4(double *state, double *unused, double *out_6216561684044621445) {
  h_4(state, unused, out_6216561684044621445);
}
void pose_H_4(double *state, double *unused, double *out_6284303352466070533) {
  H_4(state, unused, out_6284303352466070533);
}
void pose_h_10(double *state, double *unused, double *out_8921172237656055896) {
  h_10(state, unused, out_8921172237656055896);
}
void pose_H_10(double *state, double *unused, double *out_4166178305681923609) {
  H_10(state, unused, out_4166178305681923609);
}
void pose_h_13(double *state, double *unused, double *out_4225136367746162929) {
  h_13(state, unused, out_4225136367746162929);
}
void pose_H_13(double *state, double *unused, double *out_1326327855850630396) {
  H_13(state, unused, out_1326327855850630396);
}
void pose_h_14(double *state, double *unused, double *out_3049593094819758450) {
  h_14(state, unused, out_3049593094819758450);
}
void pose_H_14(double *state, double *unused, double *out_2321062496126586004) {
  H_14(state, unused, out_2321062496126586004);
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
