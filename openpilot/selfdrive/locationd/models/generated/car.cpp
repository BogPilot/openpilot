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
void err_fun(double *nom_x, double *delta_x, double *out_8321129926226555584) {
   out_8321129926226555584[0] = delta_x[0] + nom_x[0];
   out_8321129926226555584[1] = delta_x[1] + nom_x[1];
   out_8321129926226555584[2] = delta_x[2] + nom_x[2];
   out_8321129926226555584[3] = delta_x[3] + nom_x[3];
   out_8321129926226555584[4] = delta_x[4] + nom_x[4];
   out_8321129926226555584[5] = delta_x[5] + nom_x[5];
   out_8321129926226555584[6] = delta_x[6] + nom_x[6];
   out_8321129926226555584[7] = delta_x[7] + nom_x[7];
   out_8321129926226555584[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_6139682872100928343) {
   out_6139682872100928343[0] = -nom_x[0] + true_x[0];
   out_6139682872100928343[1] = -nom_x[1] + true_x[1];
   out_6139682872100928343[2] = -nom_x[2] + true_x[2];
   out_6139682872100928343[3] = -nom_x[3] + true_x[3];
   out_6139682872100928343[4] = -nom_x[4] + true_x[4];
   out_6139682872100928343[5] = -nom_x[5] + true_x[5];
   out_6139682872100928343[6] = -nom_x[6] + true_x[6];
   out_6139682872100928343[7] = -nom_x[7] + true_x[7];
   out_6139682872100928343[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_34076242180925360) {
   out_34076242180925360[0] = 1.0;
   out_34076242180925360[1] = 0.0;
   out_34076242180925360[2] = 0.0;
   out_34076242180925360[3] = 0.0;
   out_34076242180925360[4] = 0.0;
   out_34076242180925360[5] = 0.0;
   out_34076242180925360[6] = 0.0;
   out_34076242180925360[7] = 0.0;
   out_34076242180925360[8] = 0.0;
   out_34076242180925360[9] = 0.0;
   out_34076242180925360[10] = 1.0;
   out_34076242180925360[11] = 0.0;
   out_34076242180925360[12] = 0.0;
   out_34076242180925360[13] = 0.0;
   out_34076242180925360[14] = 0.0;
   out_34076242180925360[15] = 0.0;
   out_34076242180925360[16] = 0.0;
   out_34076242180925360[17] = 0.0;
   out_34076242180925360[18] = 0.0;
   out_34076242180925360[19] = 0.0;
   out_34076242180925360[20] = 1.0;
   out_34076242180925360[21] = 0.0;
   out_34076242180925360[22] = 0.0;
   out_34076242180925360[23] = 0.0;
   out_34076242180925360[24] = 0.0;
   out_34076242180925360[25] = 0.0;
   out_34076242180925360[26] = 0.0;
   out_34076242180925360[27] = 0.0;
   out_34076242180925360[28] = 0.0;
   out_34076242180925360[29] = 0.0;
   out_34076242180925360[30] = 1.0;
   out_34076242180925360[31] = 0.0;
   out_34076242180925360[32] = 0.0;
   out_34076242180925360[33] = 0.0;
   out_34076242180925360[34] = 0.0;
   out_34076242180925360[35] = 0.0;
   out_34076242180925360[36] = 0.0;
   out_34076242180925360[37] = 0.0;
   out_34076242180925360[38] = 0.0;
   out_34076242180925360[39] = 0.0;
   out_34076242180925360[40] = 1.0;
   out_34076242180925360[41] = 0.0;
   out_34076242180925360[42] = 0.0;
   out_34076242180925360[43] = 0.0;
   out_34076242180925360[44] = 0.0;
   out_34076242180925360[45] = 0.0;
   out_34076242180925360[46] = 0.0;
   out_34076242180925360[47] = 0.0;
   out_34076242180925360[48] = 0.0;
   out_34076242180925360[49] = 0.0;
   out_34076242180925360[50] = 1.0;
   out_34076242180925360[51] = 0.0;
   out_34076242180925360[52] = 0.0;
   out_34076242180925360[53] = 0.0;
   out_34076242180925360[54] = 0.0;
   out_34076242180925360[55] = 0.0;
   out_34076242180925360[56] = 0.0;
   out_34076242180925360[57] = 0.0;
   out_34076242180925360[58] = 0.0;
   out_34076242180925360[59] = 0.0;
   out_34076242180925360[60] = 1.0;
   out_34076242180925360[61] = 0.0;
   out_34076242180925360[62] = 0.0;
   out_34076242180925360[63] = 0.0;
   out_34076242180925360[64] = 0.0;
   out_34076242180925360[65] = 0.0;
   out_34076242180925360[66] = 0.0;
   out_34076242180925360[67] = 0.0;
   out_34076242180925360[68] = 0.0;
   out_34076242180925360[69] = 0.0;
   out_34076242180925360[70] = 1.0;
   out_34076242180925360[71] = 0.0;
   out_34076242180925360[72] = 0.0;
   out_34076242180925360[73] = 0.0;
   out_34076242180925360[74] = 0.0;
   out_34076242180925360[75] = 0.0;
   out_34076242180925360[76] = 0.0;
   out_34076242180925360[77] = 0.0;
   out_34076242180925360[78] = 0.0;
   out_34076242180925360[79] = 0.0;
   out_34076242180925360[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_2158642534494546935) {
   out_2158642534494546935[0] = state[0];
   out_2158642534494546935[1] = state[1];
   out_2158642534494546935[2] = state[2];
   out_2158642534494546935[3] = state[3];
   out_2158642534494546935[4] = state[4];
   out_2158642534494546935[5] = dt*(stiffness_front*(-state[2] - state[3] + state[7])*state[0]/state[1] + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/state[4] + ((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4])*state[6] - 9.8100000000000005*state[8]) + state[5];
   out_2158642534494546935[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_2158642534494546935[7] = state[7];
   out_2158642534494546935[8] = state[8];
}
void F_fun(double *state, double dt, double *out_5954463895015124794) {
   out_5954463895015124794[0] = 1;
   out_5954463895015124794[1] = 0;
   out_5954463895015124794[2] = 0;
   out_5954463895015124794[3] = 0;
   out_5954463895015124794[4] = 0;
   out_5954463895015124794[5] = 0;
   out_5954463895015124794[6] = 0;
   out_5954463895015124794[7] = 0;
   out_5954463895015124794[8] = 0;
   out_5954463895015124794[9] = 0;
   out_5954463895015124794[10] = 1;
   out_5954463895015124794[11] = 0;
   out_5954463895015124794[12] = 0;
   out_5954463895015124794[13] = 0;
   out_5954463895015124794[14] = 0;
   out_5954463895015124794[15] = 0;
   out_5954463895015124794[16] = 0;
   out_5954463895015124794[17] = 0;
   out_5954463895015124794[18] = 0;
   out_5954463895015124794[19] = 0;
   out_5954463895015124794[20] = 1;
   out_5954463895015124794[21] = 0;
   out_5954463895015124794[22] = 0;
   out_5954463895015124794[23] = 0;
   out_5954463895015124794[24] = 0;
   out_5954463895015124794[25] = 0;
   out_5954463895015124794[26] = 0;
   out_5954463895015124794[27] = 0;
   out_5954463895015124794[28] = 0;
   out_5954463895015124794[29] = 0;
   out_5954463895015124794[30] = 1;
   out_5954463895015124794[31] = 0;
   out_5954463895015124794[32] = 0;
   out_5954463895015124794[33] = 0;
   out_5954463895015124794[34] = 0;
   out_5954463895015124794[35] = 0;
   out_5954463895015124794[36] = 0;
   out_5954463895015124794[37] = 0;
   out_5954463895015124794[38] = 0;
   out_5954463895015124794[39] = 0;
   out_5954463895015124794[40] = 1;
   out_5954463895015124794[41] = 0;
   out_5954463895015124794[42] = 0;
   out_5954463895015124794[43] = 0;
   out_5954463895015124794[44] = 0;
   out_5954463895015124794[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/state[1] + (-stiffness_front - stiffness_rear)*state[5]/state[4] + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/state[4]);
   out_5954463895015124794[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/pow(state[1], 2);
   out_5954463895015124794[47] = -dt*stiffness_front*state[0]/state[1];
   out_5954463895015124794[48] = -dt*stiffness_front*state[0]/state[1];
   out_5954463895015124794[49] = dt*(-(-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/pow(state[4], 2) + (-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/pow(state[4], 2) - 1)*state[6]);
   out_5954463895015124794[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/state[4] + 1;
   out_5954463895015124794[51] = dt*((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4]);
   out_5954463895015124794[52] = dt*stiffness_front*state[0]/state[1];
   out_5954463895015124794[53] = -9.8100000000000005*dt;
   out_5954463895015124794[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_5954463895015124794[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_5954463895015124794[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5954463895015124794[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5954463895015124794[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_5954463895015124794[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_5954463895015124794[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_5954463895015124794[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_5954463895015124794[62] = 0;
   out_5954463895015124794[63] = 0;
   out_5954463895015124794[64] = 0;
   out_5954463895015124794[65] = 0;
   out_5954463895015124794[66] = 0;
   out_5954463895015124794[67] = 0;
   out_5954463895015124794[68] = 0;
   out_5954463895015124794[69] = 0;
   out_5954463895015124794[70] = 1;
   out_5954463895015124794[71] = 0;
   out_5954463895015124794[72] = 0;
   out_5954463895015124794[73] = 0;
   out_5954463895015124794[74] = 0;
   out_5954463895015124794[75] = 0;
   out_5954463895015124794[76] = 0;
   out_5954463895015124794[77] = 0;
   out_5954463895015124794[78] = 0;
   out_5954463895015124794[79] = 0;
   out_5954463895015124794[80] = 1;
}
void h_25(double *state, double *unused, double *out_2719516181999733219) {
   out_2719516181999733219[0] = state[6];
}
void H_25(double *state, double *unused, double *out_1270262868011046260) {
   out_1270262868011046260[0] = 0;
   out_1270262868011046260[1] = 0;
   out_1270262868011046260[2] = 0;
   out_1270262868011046260[3] = 0;
   out_1270262868011046260[4] = 0;
   out_1270262868011046260[5] = 0;
   out_1270262868011046260[6] = 1;
   out_1270262868011046260[7] = 0;
   out_1270262868011046260[8] = 0;
}
void h_24(double *state, double *unused, double *out_70937688792751635) {
   out_70937688792751635[0] = state[4];
   out_70937688792751635[1] = state[5];
}
void H_24(double *state, double *unused, double *out_4541122763011730705) {
   out_4541122763011730705[0] = 0;
   out_4541122763011730705[1] = 0;
   out_4541122763011730705[2] = 0;
   out_4541122763011730705[3] = 0;
   out_4541122763011730705[4] = 1;
   out_4541122763011730705[5] = 0;
   out_4541122763011730705[6] = 0;
   out_4541122763011730705[7] = 0;
   out_4541122763011730705[8] = 0;
   out_4541122763011730705[9] = 0;
   out_4541122763011730705[10] = 0;
   out_4541122763011730705[11] = 0;
   out_4541122763011730705[12] = 0;
   out_4541122763011730705[13] = 0;
   out_4541122763011730705[14] = 1;
   out_4541122763011730705[15] = 0;
   out_4541122763011730705[16] = 0;
   out_4541122763011730705[17] = 0;
}
void h_30(double *state, double *unused, double *out_7963962634889145956) {
   out_7963962634889145956[0] = state[4];
}
void H_30(double *state, double *unused, double *out_1399601815154286330) {
   out_1399601815154286330[0] = 0;
   out_1399601815154286330[1] = 0;
   out_1399601815154286330[2] = 0;
   out_1399601815154286330[3] = 0;
   out_1399601815154286330[4] = 1;
   out_1399601815154286330[5] = 0;
   out_1399601815154286330[6] = 0;
   out_1399601815154286330[7] = 0;
   out_1399601815154286330[8] = 0;
}
void h_26(double *state, double *unused, double *out_4724796524826667704) {
   out_4724796524826667704[0] = state[7];
}
void H_26(double *state, double *unused, double *out_613408803900734356) {
   out_613408803900734356[0] = 0;
   out_613408803900734356[1] = 0;
   out_613408803900734356[2] = 0;
   out_613408803900734356[3] = 0;
   out_613408803900734356[4] = 0;
   out_613408803900734356[5] = 0;
   out_613408803900734356[6] = 0;
   out_613408803900734356[7] = 1;
   out_613408803900734356[8] = 0;
}
void h_27(double *state, double *unused, double *out_5308597199970421718) {
   out_5308597199970421718[0] = state[3];
}
void H_27(double *state, double *unused, double *out_3574365126954711241) {
   out_3574365126954711241[0] = 0;
   out_3574365126954711241[1] = 0;
   out_3574365126954711241[2] = 0;
   out_3574365126954711241[3] = 1;
   out_3574365126954711241[4] = 0;
   out_3574365126954711241[5] = 0;
   out_3574365126954711241[6] = 0;
   out_3574365126954711241[7] = 0;
   out_3574365126954711241[8] = 0;
}
void h_29(double *state, double *unused, double *out_5481108171159560015) {
   out_5481108171159560015[0] = state[1];
}
void H_29(double *state, double *unused, double *out_889370470839894146) {
   out_889370470839894146[0] = 0;
   out_889370470839894146[1] = 1;
   out_889370470839894146[2] = 0;
   out_889370470839894146[3] = 0;
   out_889370470839894146[4] = 0;
   out_889370470839894146[5] = 0;
   out_889370470839894146[6] = 0;
   out_889370470839894146[7] = 0;
   out_889370470839894146[8] = 0;
}
void h_28(double *state, double *unused, double *out_346217202289128486) {
   out_346217202289128486[0] = state[0];
}
void H_28(double *state, double *unused, double *out_5971769487909424720) {
   out_5971769487909424720[0] = 1;
   out_5971769487909424720[1] = 0;
   out_5971769487909424720[2] = 0;
   out_5971769487909424720[3] = 0;
   out_5971769487909424720[4] = 0;
   out_5971769487909424720[5] = 0;
   out_5971769487909424720[6] = 0;
   out_5971769487909424720[7] = 0;
   out_5971769487909424720[8] = 0;
}
void h_31(double *state, double *unused, double *out_7845955240955769212) {
   out_7845955240955769212[0] = state[8];
}
void H_31(double *state, double *unused, double *out_1239616906134085832) {
   out_1239616906134085832[0] = 0;
   out_1239616906134085832[1] = 0;
   out_1239616906134085832[2] = 0;
   out_1239616906134085832[3] = 0;
   out_1239616906134085832[4] = 0;
   out_1239616906134085832[5] = 0;
   out_1239616906134085832[6] = 0;
   out_1239616906134085832[7] = 0;
   out_1239616906134085832[8] = 1;
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
void car_err_fun(double *nom_x, double *delta_x, double *out_8321129926226555584) {
  err_fun(nom_x, delta_x, out_8321129926226555584);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_6139682872100928343) {
  inv_err_fun(nom_x, true_x, out_6139682872100928343);
}
void car_H_mod_fun(double *state, double *out_34076242180925360) {
  H_mod_fun(state, out_34076242180925360);
}
void car_f_fun(double *state, double dt, double *out_2158642534494546935) {
  f_fun(state,  dt, out_2158642534494546935);
}
void car_F_fun(double *state, double dt, double *out_5954463895015124794) {
  F_fun(state,  dt, out_5954463895015124794);
}
void car_h_25(double *state, double *unused, double *out_2719516181999733219) {
  h_25(state, unused, out_2719516181999733219);
}
void car_H_25(double *state, double *unused, double *out_1270262868011046260) {
  H_25(state, unused, out_1270262868011046260);
}
void car_h_24(double *state, double *unused, double *out_70937688792751635) {
  h_24(state, unused, out_70937688792751635);
}
void car_H_24(double *state, double *unused, double *out_4541122763011730705) {
  H_24(state, unused, out_4541122763011730705);
}
void car_h_30(double *state, double *unused, double *out_7963962634889145956) {
  h_30(state, unused, out_7963962634889145956);
}
void car_H_30(double *state, double *unused, double *out_1399601815154286330) {
  H_30(state, unused, out_1399601815154286330);
}
void car_h_26(double *state, double *unused, double *out_4724796524826667704) {
  h_26(state, unused, out_4724796524826667704);
}
void car_H_26(double *state, double *unused, double *out_613408803900734356) {
  H_26(state, unused, out_613408803900734356);
}
void car_h_27(double *state, double *unused, double *out_5308597199970421718) {
  h_27(state, unused, out_5308597199970421718);
}
void car_H_27(double *state, double *unused, double *out_3574365126954711241) {
  H_27(state, unused, out_3574365126954711241);
}
void car_h_29(double *state, double *unused, double *out_5481108171159560015) {
  h_29(state, unused, out_5481108171159560015);
}
void car_H_29(double *state, double *unused, double *out_889370470839894146) {
  H_29(state, unused, out_889370470839894146);
}
void car_h_28(double *state, double *unused, double *out_346217202289128486) {
  h_28(state, unused, out_346217202289128486);
}
void car_H_28(double *state, double *unused, double *out_5971769487909424720) {
  H_28(state, unused, out_5971769487909424720);
}
void car_h_31(double *state, double *unused, double *out_7845955240955769212) {
  h_31(state, unused, out_7845955240955769212);
}
void car_H_31(double *state, double *unused, double *out_1239616906134085832) {
  H_31(state, unused, out_1239616906134085832);
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
