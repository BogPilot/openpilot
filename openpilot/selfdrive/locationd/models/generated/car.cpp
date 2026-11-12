#include "car.h"

namespace {
#define DIM 9
#define EDIM 9
#define MEDIM 9
typedef void (*Hfun)(double *, double *, double *);

double rotational_inertia;

void set_rotational_inertia(double x){ rotational_inertia = x;}

double center_to_front;

void set_center_to_front(double x){ center_to_front = x;}

double center_to_rear;

void set_center_to_rear(double x){ center_to_rear = x;}

double stiffness_front;

void set_stiffness_front(double x){ stiffness_front = x;}

double stiffness_rear;

void set_stiffness_rear(double x){ stiffness_rear = x;}
const static double MAHA_THRESH_25 = 3.8414588206941227;
const static double MAHA_THRESH_24 = 5.991464547107981;
const static double MAHA_THRESH_30 = 3.8414588206941227;
const static double MAHA_THRESH_26 = 3.8414588206941227;
const static double MAHA_THRESH_27 = 3.8414588206941227;
const static double MAHA_THRESH_29 = 3.8414588206941227;
const static double MAHA_THRESH_28 = 3.8414588206941227;
const static double MAHA_THRESH_31 = 3.8414588206941227;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_9155965617354986968) {
   out_9155965617354986968[0] = delta_x[0] + nom_x[0];
   out_9155965617354986968[1] = delta_x[1] + nom_x[1];
   out_9155965617354986968[2] = delta_x[2] + nom_x[2];
   out_9155965617354986968[3] = delta_x[3] + nom_x[3];
   out_9155965617354986968[4] = delta_x[4] + nom_x[4];
   out_9155965617354986968[5] = delta_x[5] + nom_x[5];
   out_9155965617354986968[6] = delta_x[6] + nom_x[6];
   out_9155965617354986968[7] = delta_x[7] + nom_x[7];
   out_9155965617354986968[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_2871414695186438168) {
   out_2871414695186438168[0] = -nom_x[0] + true_x[0];
   out_2871414695186438168[1] = -nom_x[1] + true_x[1];
   out_2871414695186438168[2] = -nom_x[2] + true_x[2];
   out_2871414695186438168[3] = -nom_x[3] + true_x[3];
   out_2871414695186438168[4] = -nom_x[4] + true_x[4];
   out_2871414695186438168[5] = -nom_x[5] + true_x[5];
   out_2871414695186438168[6] = -nom_x[6] + true_x[6];
   out_2871414695186438168[7] = -nom_x[7] + true_x[7];
   out_2871414695186438168[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_8509207105295575047) {
   out_8509207105295575047[0] = 1.0;
   out_8509207105295575047[1] = 0.0;
   out_8509207105295575047[2] = 0.0;
   out_8509207105295575047[3] = 0.0;
   out_8509207105295575047[4] = 0.0;
   out_8509207105295575047[5] = 0.0;
   out_8509207105295575047[6] = 0.0;
   out_8509207105295575047[7] = 0.0;
   out_8509207105295575047[8] = 0.0;
   out_8509207105295575047[9] = 0.0;
   out_8509207105295575047[10] = 1.0;
   out_8509207105295575047[11] = 0.0;
   out_8509207105295575047[12] = 0.0;
   out_8509207105295575047[13] = 0.0;
   out_8509207105295575047[14] = 0.0;
   out_8509207105295575047[15] = 0.0;
   out_8509207105295575047[16] = 0.0;
   out_8509207105295575047[17] = 0.0;
   out_8509207105295575047[18] = 0.0;
   out_8509207105295575047[19] = 0.0;
   out_8509207105295575047[20] = 1.0;
   out_8509207105295575047[21] = 0.0;
   out_8509207105295575047[22] = 0.0;
   out_8509207105295575047[23] = 0.0;
   out_8509207105295575047[24] = 0.0;
   out_8509207105295575047[25] = 0.0;
   out_8509207105295575047[26] = 0.0;
   out_8509207105295575047[27] = 0.0;
   out_8509207105295575047[28] = 0.0;
   out_8509207105295575047[29] = 0.0;
   out_8509207105295575047[30] = 1.0;
   out_8509207105295575047[31] = 0.0;
   out_8509207105295575047[32] = 0.0;
   out_8509207105295575047[33] = 0.0;
   out_8509207105295575047[34] = 0.0;
   out_8509207105295575047[35] = 0.0;
   out_8509207105295575047[36] = 0.0;
   out_8509207105295575047[37] = 0.0;
   out_8509207105295575047[38] = 0.0;
   out_8509207105295575047[39] = 0.0;
   out_8509207105295575047[40] = 1.0;
   out_8509207105295575047[41] = 0.0;
   out_8509207105295575047[42] = 0.0;
   out_8509207105295575047[43] = 0.0;
   out_8509207105295575047[44] = 0.0;
   out_8509207105295575047[45] = 0.0;
   out_8509207105295575047[46] = 0.0;
   out_8509207105295575047[47] = 0.0;
   out_8509207105295575047[48] = 0.0;
   out_8509207105295575047[49] = 0.0;
   out_8509207105295575047[50] = 1.0;
   out_8509207105295575047[51] = 0.0;
   out_8509207105295575047[52] = 0.0;
   out_8509207105295575047[53] = 0.0;
   out_8509207105295575047[54] = 0.0;
   out_8509207105295575047[55] = 0.0;
   out_8509207105295575047[56] = 0.0;
   out_8509207105295575047[57] = 0.0;
   out_8509207105295575047[58] = 0.0;
   out_8509207105295575047[59] = 0.0;
   out_8509207105295575047[60] = 1.0;
   out_8509207105295575047[61] = 0.0;
   out_8509207105295575047[62] = 0.0;
   out_8509207105295575047[63] = 0.0;
   out_8509207105295575047[64] = 0.0;
   out_8509207105295575047[65] = 0.0;
   out_8509207105295575047[66] = 0.0;
   out_8509207105295575047[67] = 0.0;
   out_8509207105295575047[68] = 0.0;
   out_8509207105295575047[69] = 0.0;
   out_8509207105295575047[70] = 1.0;
   out_8509207105295575047[71] = 0.0;
   out_8509207105295575047[72] = 0.0;
   out_8509207105295575047[73] = 0.0;
   out_8509207105295575047[74] = 0.0;
   out_8509207105295575047[75] = 0.0;
   out_8509207105295575047[76] = 0.0;
   out_8509207105295575047[77] = 0.0;
   out_8509207105295575047[78] = 0.0;
   out_8509207105295575047[79] = 0.0;
   out_8509207105295575047[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_4836537562228931990) {
   out_4836537562228931990[0] = state[0];
   out_4836537562228931990[1] = state[1];
   out_4836537562228931990[2] = state[2];
   out_4836537562228931990[3] = state[3];
   out_4836537562228931990[4] = state[4];
   out_4836537562228931990[5] = dt*(stiffness_front*(-state[2] - state[3] + state[7])*state[0]/state[1] + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/state[4] + ((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4])*state[6] - 9.8100000000000005*state[8]) + state[5];
   out_4836537562228931990[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_4836537562228931990[7] = state[7];
   out_4836537562228931990[8] = state[8];
}
void F_fun(double *state, double dt, double *out_6757899816353951324) {
   out_6757899816353951324[0] = 1;
   out_6757899816353951324[1] = 0;
   out_6757899816353951324[2] = 0;
   out_6757899816353951324[3] = 0;
   out_6757899816353951324[4] = 0;
   out_6757899816353951324[5] = 0;
   out_6757899816353951324[6] = 0;
   out_6757899816353951324[7] = 0;
   out_6757899816353951324[8] = 0;
   out_6757899816353951324[9] = 0;
   out_6757899816353951324[10] = 1;
   out_6757899816353951324[11] = 0;
   out_6757899816353951324[12] = 0;
   out_6757899816353951324[13] = 0;
   out_6757899816353951324[14] = 0;
   out_6757899816353951324[15] = 0;
   out_6757899816353951324[16] = 0;
   out_6757899816353951324[17] = 0;
   out_6757899816353951324[18] = 0;
   out_6757899816353951324[19] = 0;
   out_6757899816353951324[20] = 1;
   out_6757899816353951324[21] = 0;
   out_6757899816353951324[22] = 0;
   out_6757899816353951324[23] = 0;
   out_6757899816353951324[24] = 0;
   out_6757899816353951324[25] = 0;
   out_6757899816353951324[26] = 0;
   out_6757899816353951324[27] = 0;
   out_6757899816353951324[28] = 0;
   out_6757899816353951324[29] = 0;
   out_6757899816353951324[30] = 1;
   out_6757899816353951324[31] = 0;
   out_6757899816353951324[32] = 0;
   out_6757899816353951324[33] = 0;
   out_6757899816353951324[34] = 0;
   out_6757899816353951324[35] = 0;
   out_6757899816353951324[36] = 0;
   out_6757899816353951324[37] = 0;
   out_6757899816353951324[38] = 0;
   out_6757899816353951324[39] = 0;
   out_6757899816353951324[40] = 1;
   out_6757899816353951324[41] = 0;
   out_6757899816353951324[42] = 0;
   out_6757899816353951324[43] = 0;
   out_6757899816353951324[44] = 0;
   out_6757899816353951324[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/state[1] + (-stiffness_front - stiffness_rear)*state[5]/state[4] + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/state[4]);
   out_6757899816353951324[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/pow(state[1], 2);
   out_6757899816353951324[47] = -dt*stiffness_front*state[0]/state[1];
   out_6757899816353951324[48] = -dt*stiffness_front*state[0]/state[1];
   out_6757899816353951324[49] = dt*(-(-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/pow(state[4], 2) + (-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/pow(state[4], 2) - 1)*state[6]);
   out_6757899816353951324[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/state[4] + 1;
   out_6757899816353951324[51] = dt*((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4]);
   out_6757899816353951324[52] = dt*stiffness_front*state[0]/state[1];
   out_6757899816353951324[53] = -9.8100000000000005*dt;
   out_6757899816353951324[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_6757899816353951324[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_6757899816353951324[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_6757899816353951324[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_6757899816353951324[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_6757899816353951324[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_6757899816353951324[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_6757899816353951324[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_6757899816353951324[62] = 0;
   out_6757899816353951324[63] = 0;
   out_6757899816353951324[64] = 0;
   out_6757899816353951324[65] = 0;
   out_6757899816353951324[66] = 0;
   out_6757899816353951324[67] = 0;
   out_6757899816353951324[68] = 0;
   out_6757899816353951324[69] = 0;
   out_6757899816353951324[70] = 1;
   out_6757899816353951324[71] = 0;
   out_6757899816353951324[72] = 0;
   out_6757899816353951324[73] = 0;
   out_6757899816353951324[74] = 0;
   out_6757899816353951324[75] = 0;
   out_6757899816353951324[76] = 0;
   out_6757899816353951324[77] = 0;
   out_6757899816353951324[78] = 0;
   out_6757899816353951324[79] = 0;
   out_6757899816353951324[80] = 1;
}
void h_25(double *state, double *unused, double *out_5636842392341776803) {
   out_5636842392341776803[0] = state[6];
}
void H_25(double *state, double *unused, double *out_8171721720410462967) {
   out_8171721720410462967[0] = 0;
   out_8171721720410462967[1] = 0;
   out_8171721720410462967[2] = 0;
   out_8171721720410462967[3] = 0;
   out_8171721720410462967[4] = 0;
   out_8171721720410462967[5] = 0;
   out_8171721720410462967[6] = 1;
   out_8171721720410462967[7] = 0;
   out_8171721720410462967[8] = 0;
}
void h_24(double *state, double *unused, double *out_8501700083487156086) {
   out_8501700083487156086[0] = state[4];
   out_8501700083487156086[1] = state[5];
}
void H_24(double *state, double *unused, double *out_2856630719622161756) {
   out_2856630719622161756[0] = 0;
   out_2856630719622161756[1] = 0;
   out_2856630719622161756[2] = 0;
   out_2856630719622161756[3] = 0;
   out_2856630719622161756[4] = 1;
   out_2856630719622161756[5] = 0;
   out_2856630719622161756[6] = 0;
   out_2856630719622161756[7] = 0;
   out_2856630719622161756[8] = 0;
   out_2856630719622161756[9] = 0;
   out_2856630719622161756[10] = 0;
   out_2856630719622161756[11] = 0;
   out_2856630719622161756[12] = 0;
   out_2856630719622161756[13] = 0;
   out_2856630719622161756[14] = 1;
   out_2856630719622161756[15] = 0;
   out_2856630719622161756[16] = 0;
   out_2856630719622161756[17] = 0;
}
void h_30(double *state, double *unused, double *out_583534790505237166) {
   out_583534790505237166[0] = state[4];
}
void H_30(double *state, double *unused, double *out_8042382773267222897) {
   out_8042382773267222897[0] = 0;
   out_8042382773267222897[1] = 0;
   out_8042382773267222897[2] = 0;
   out_8042382773267222897[3] = 0;
   out_8042382773267222897[4] = 1;
   out_8042382773267222897[5] = 0;
   out_8042382773267222897[6] = 0;
   out_8042382773267222897[7] = 0;
   out_8042382773267222897[8] = 0;
}
void h_26(double *state, double *unused, double *out_19781094171240351) {
   out_19781094171240351[0] = state[7];
}
void H_26(double *state, double *unused, double *out_8828575784520774871) {
   out_8828575784520774871[0] = 0;
   out_8828575784520774871[1] = 0;
   out_8828575784520774871[2] = 0;
   out_8828575784520774871[3] = 0;
   out_8828575784520774871[4] = 0;
   out_8828575784520774871[5] = 0;
   out_8828575784520774871[6] = 0;
   out_8828575784520774871[7] = 1;
   out_8828575784520774871[8] = 0;
}
void h_27(double *state, double *unused, double *out_635169124680931158) {
   out_635169124680931158[0] = state[3];
}
void H_27(double *state, double *unused, double *out_5867619461466797986) {
   out_5867619461466797986[0] = 0;
   out_5867619461466797986[1] = 0;
   out_5867619461466797986[2] = 0;
   out_5867619461466797986[3] = 1;
   out_5867619461466797986[4] = 0;
   out_5867619461466797986[5] = 0;
   out_5867619461466797986[6] = 0;
   out_5867619461466797986[7] = 0;
   out_5867619461466797986[8] = 0;
}
void h_29(double *state, double *unused, double *out_8398434381501603599) {
   out_8398434381501603599[0] = state[1];
}
void H_29(double *state, double *unused, double *out_8552614117581615081) {
   out_8552614117581615081[0] = 0;
   out_8552614117581615081[1] = 1;
   out_8552614117581615081[2] = 0;
   out_8552614117581615081[3] = 0;
   out_8552614117581615081[4] = 0;
   out_8552614117581615081[5] = 0;
   out_8552614117581615081[6] = 0;
   out_8552614117581615081[7] = 0;
   out_8552614117581615081[8] = 0;
}
void h_28(double *state, double *unused, double *out_3239574445489628809) {
   out_3239574445489628809[0] = state[0];
}
void H_28(double *state, double *unused, double *out_3470215100512084507) {
   out_3470215100512084507[0] = 1;
   out_3470215100512084507[1] = 0;
   out_3470215100512084507[2] = 0;
   out_3470215100512084507[3] = 0;
   out_3470215100512084507[4] = 0;
   out_3470215100512084507[5] = 0;
   out_3470215100512084507[6] = 0;
   out_3470215100512084507[7] = 0;
   out_3470215100512084507[8] = 0;
}
void h_31(double *state, double *unused, double *out_2859818288921963189) {
   out_2859818288921963189[0] = state[8];
}
void H_31(double *state, double *unused, double *out_8202367682287423395) {
   out_8202367682287423395[0] = 0;
   out_8202367682287423395[1] = 0;
   out_8202367682287423395[2] = 0;
   out_8202367682287423395[3] = 0;
   out_8202367682287423395[4] = 0;
   out_8202367682287423395[5] = 0;
   out_8202367682287423395[6] = 0;
   out_8202367682287423395[7] = 0;
   out_8202367682287423395[8] = 1;
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

void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_25, H_25, NULL, in_z, in_R, in_ea, MAHA_THRESH_25);
}
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<2, 3, 0>(in_x, in_P, h_24, H_24, NULL, in_z, in_R, in_ea, MAHA_THRESH_24);
}
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_30, H_30, NULL, in_z, in_R, in_ea, MAHA_THRESH_30);
}
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_26, H_26, NULL, in_z, in_R, in_ea, MAHA_THRESH_26);
}
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_27, H_27, NULL, in_z, in_R, in_ea, MAHA_THRESH_27);
}
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_29, H_29, NULL, in_z, in_R, in_ea, MAHA_THRESH_29);
}
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_28, H_28, NULL, in_z, in_R, in_ea, MAHA_THRESH_28);
}
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_31, H_31, NULL, in_z, in_R, in_ea, MAHA_THRESH_31);
}
void car_err_fun(double *nom_x, double *delta_x, double *out_9155965617354986968) {
  err_fun(nom_x, delta_x, out_9155965617354986968);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_2871414695186438168) {
  inv_err_fun(nom_x, true_x, out_2871414695186438168);
}
void car_H_mod_fun(double *state, double *out_8509207105295575047) {
  H_mod_fun(state, out_8509207105295575047);
}
void car_f_fun(double *state, double dt, double *out_4836537562228931990) {
  f_fun(state,  dt, out_4836537562228931990);
}
void car_F_fun(double *state, double dt, double *out_6757899816353951324) {
  F_fun(state,  dt, out_6757899816353951324);
}
void car_h_25(double *state, double *unused, double *out_5636842392341776803) {
  h_25(state, unused, out_5636842392341776803);
}
void car_H_25(double *state, double *unused, double *out_8171721720410462967) {
  H_25(state, unused, out_8171721720410462967);
}
void car_h_24(double *state, double *unused, double *out_8501700083487156086) {
  h_24(state, unused, out_8501700083487156086);
}
void car_H_24(double *state, double *unused, double *out_2856630719622161756) {
  H_24(state, unused, out_2856630719622161756);
}
void car_h_30(double *state, double *unused, double *out_583534790505237166) {
  h_30(state, unused, out_583534790505237166);
}
void car_H_30(double *state, double *unused, double *out_8042382773267222897) {
  H_30(state, unused, out_8042382773267222897);
}
void car_h_26(double *state, double *unused, double *out_19781094171240351) {
  h_26(state, unused, out_19781094171240351);
}
void car_H_26(double *state, double *unused, double *out_8828575784520774871) {
  H_26(state, unused, out_8828575784520774871);
}
void car_h_27(double *state, double *unused, double *out_635169124680931158) {
  h_27(state, unused, out_635169124680931158);
}
void car_H_27(double *state, double *unused, double *out_5867619461466797986) {
  H_27(state, unused, out_5867619461466797986);
}
void car_h_29(double *state, double *unused, double *out_8398434381501603599) {
  h_29(state, unused, out_8398434381501603599);
}
void car_H_29(double *state, double *unused, double *out_8552614117581615081) {
  H_29(state, unused, out_8552614117581615081);
}
void car_h_28(double *state, double *unused, double *out_3239574445489628809) {
  h_28(state, unused, out_3239574445489628809);
}
void car_H_28(double *state, double *unused, double *out_3470215100512084507) {
  H_28(state, unused, out_3470215100512084507);
}
void car_h_31(double *state, double *unused, double *out_2859818288921963189) {
  h_31(state, unused, out_2859818288921963189);
}
void car_H_31(double *state, double *unused, double *out_8202367682287423395) {
  H_31(state, unused, out_8202367682287423395);
}
void car_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
void car_set_rotational_inertia(double x) {
  set_rotational_inertia(x);
}
void car_set_center_to_front(double x) {
  set_center_to_front(x);
}
void car_set_center_to_rear(double x) {
  set_center_to_rear(x);
}
void car_set_stiffness_front(double x) {
  set_stiffness_front(x);
}
void car_set_stiffness_rear(double x) {
  set_stiffness_rear(x);
}
}

const EKF car = {
  .name = "car",
  .kinds = { 25, 24, 30, 26, 27, 29, 28, 31 },
  .feature_kinds = {  },
  .f_fun = car_f_fun,
  .F_fun = car_F_fun,
  .err_fun = car_err_fun,
  .inv_err_fun = car_inv_err_fun,
  .H_mod_fun = car_H_mod_fun,
  .predict = car_predict,
  .hs = {
    { 25, car_h_25 },
    { 24, car_h_24 },
    { 30, car_h_30 },
    { 26, car_h_26 },
    { 27, car_h_27 },
    { 29, car_h_29 },
    { 28, car_h_28 },
    { 31, car_h_31 },
  },
  .Hs = {
    { 25, car_H_25 },
    { 24, car_H_24 },
    { 30, car_H_30 },
    { 26, car_H_26 },
    { 27, car_H_27 },
    { 29, car_H_29 },
    { 28, car_H_28 },
    { 31, car_H_31 },
  },
  .updates = {
    { 25, car_update_25 },
    { 24, car_update_24 },
    { 30, car_update_30 },
    { 26, car_update_26 },
    { 27, car_update_27 },
    { 29, car_update_29 },
    { 28, car_update_28 },
    { 31, car_update_31 },
  },
  .Hes = {
  },
  .sets = {
    { "rotational_inertia", car_set_rotational_inertia },
    { "center_to_front", car_set_center_to_front },
    { "center_to_rear", car_set_center_to_rear },
    { "stiffness_front", car_set_stiffness_front },
    { "stiffness_rear", car_set_stiffness_rear },
  },
  .extra_routines = {
  },
};

ekf_lib_init(car)
