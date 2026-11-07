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
void err_fun(double *nom_x, double *delta_x, double *out_4975635636005312372) {
   out_4975635636005312372[0] = delta_x[0] + nom_x[0];
   out_4975635636005312372[1] = delta_x[1] + nom_x[1];
   out_4975635636005312372[2] = delta_x[2] + nom_x[2];
   out_4975635636005312372[3] = delta_x[3] + nom_x[3];
   out_4975635636005312372[4] = delta_x[4] + nom_x[4];
   out_4975635636005312372[5] = delta_x[5] + nom_x[5];
   out_4975635636005312372[6] = delta_x[6] + nom_x[6];
   out_4975635636005312372[7] = delta_x[7] + nom_x[7];
   out_4975635636005312372[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_5810940517248718795) {
   out_5810940517248718795[0] = -nom_x[0] + true_x[0];
   out_5810940517248718795[1] = -nom_x[1] + true_x[1];
   out_5810940517248718795[2] = -nom_x[2] + true_x[2];
   out_5810940517248718795[3] = -nom_x[3] + true_x[3];
   out_5810940517248718795[4] = -nom_x[4] + true_x[4];
   out_5810940517248718795[5] = -nom_x[5] + true_x[5];
   out_5810940517248718795[6] = -nom_x[6] + true_x[6];
   out_5810940517248718795[7] = -nom_x[7] + true_x[7];
   out_5810940517248718795[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_2279184306914852573) {
   out_2279184306914852573[0] = 1.0;
   out_2279184306914852573[1] = 0.0;
   out_2279184306914852573[2] = 0.0;
   out_2279184306914852573[3] = 0.0;
   out_2279184306914852573[4] = 0.0;
   out_2279184306914852573[5] = 0.0;
   out_2279184306914852573[6] = 0.0;
   out_2279184306914852573[7] = 0.0;
   out_2279184306914852573[8] = 0.0;
   out_2279184306914852573[9] = 0.0;
   out_2279184306914852573[10] = 1.0;
   out_2279184306914852573[11] = 0.0;
   out_2279184306914852573[12] = 0.0;
   out_2279184306914852573[13] = 0.0;
   out_2279184306914852573[14] = 0.0;
   out_2279184306914852573[15] = 0.0;
   out_2279184306914852573[16] = 0.0;
   out_2279184306914852573[17] = 0.0;
   out_2279184306914852573[18] = 0.0;
   out_2279184306914852573[19] = 0.0;
   out_2279184306914852573[20] = 1.0;
   out_2279184306914852573[21] = 0.0;
   out_2279184306914852573[22] = 0.0;
   out_2279184306914852573[23] = 0.0;
   out_2279184306914852573[24] = 0.0;
   out_2279184306914852573[25] = 0.0;
   out_2279184306914852573[26] = 0.0;
   out_2279184306914852573[27] = 0.0;
   out_2279184306914852573[28] = 0.0;
   out_2279184306914852573[29] = 0.0;
   out_2279184306914852573[30] = 1.0;
   out_2279184306914852573[31] = 0.0;
   out_2279184306914852573[32] = 0.0;
   out_2279184306914852573[33] = 0.0;
   out_2279184306914852573[34] = 0.0;
   out_2279184306914852573[35] = 0.0;
   out_2279184306914852573[36] = 0.0;
   out_2279184306914852573[37] = 0.0;
   out_2279184306914852573[38] = 0.0;
   out_2279184306914852573[39] = 0.0;
   out_2279184306914852573[40] = 1.0;
   out_2279184306914852573[41] = 0.0;
   out_2279184306914852573[42] = 0.0;
   out_2279184306914852573[43] = 0.0;
   out_2279184306914852573[44] = 0.0;
   out_2279184306914852573[45] = 0.0;
   out_2279184306914852573[46] = 0.0;
   out_2279184306914852573[47] = 0.0;
   out_2279184306914852573[48] = 0.0;
   out_2279184306914852573[49] = 0.0;
   out_2279184306914852573[50] = 1.0;
   out_2279184306914852573[51] = 0.0;
   out_2279184306914852573[52] = 0.0;
   out_2279184306914852573[53] = 0.0;
   out_2279184306914852573[54] = 0.0;
   out_2279184306914852573[55] = 0.0;
   out_2279184306914852573[56] = 0.0;
   out_2279184306914852573[57] = 0.0;
   out_2279184306914852573[58] = 0.0;
   out_2279184306914852573[59] = 0.0;
   out_2279184306914852573[60] = 1.0;
   out_2279184306914852573[61] = 0.0;
   out_2279184306914852573[62] = 0.0;
   out_2279184306914852573[63] = 0.0;
   out_2279184306914852573[64] = 0.0;
   out_2279184306914852573[65] = 0.0;
   out_2279184306914852573[66] = 0.0;
   out_2279184306914852573[67] = 0.0;
   out_2279184306914852573[68] = 0.0;
   out_2279184306914852573[69] = 0.0;
   out_2279184306914852573[70] = 1.0;
   out_2279184306914852573[71] = 0.0;
   out_2279184306914852573[72] = 0.0;
   out_2279184306914852573[73] = 0.0;
   out_2279184306914852573[74] = 0.0;
   out_2279184306914852573[75] = 0.0;
   out_2279184306914852573[76] = 0.0;
   out_2279184306914852573[77] = 0.0;
   out_2279184306914852573[78] = 0.0;
   out_2279184306914852573[79] = 0.0;
   out_2279184306914852573[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_2316200443245060609) {
   out_2316200443245060609[0] = state[0];
   out_2316200443245060609[1] = state[1];
   out_2316200443245060609[2] = state[2];
   out_2316200443245060609[3] = state[3];
   out_2316200443245060609[4] = state[4];
   out_2316200443245060609[5] = dt*(stiffness_front*(-state[2] - state[3] + state[7])*state[0]/state[1] + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/state[4] + ((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4])*state[6] - 9.8100000000000005*state[8]) + state[5];
   out_2316200443245060609[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_2316200443245060609[7] = state[7];
   out_2316200443245060609[8] = state[8];
}
void F_fun(double *state, double dt, double *out_9022909277376252601) {
   out_9022909277376252601[0] = 1;
   out_9022909277376252601[1] = 0;
   out_9022909277376252601[2] = 0;
   out_9022909277376252601[3] = 0;
   out_9022909277376252601[4] = 0;
   out_9022909277376252601[5] = 0;
   out_9022909277376252601[6] = 0;
   out_9022909277376252601[7] = 0;
   out_9022909277376252601[8] = 0;
   out_9022909277376252601[9] = 0;
   out_9022909277376252601[10] = 1;
   out_9022909277376252601[11] = 0;
   out_9022909277376252601[12] = 0;
   out_9022909277376252601[13] = 0;
   out_9022909277376252601[14] = 0;
   out_9022909277376252601[15] = 0;
   out_9022909277376252601[16] = 0;
   out_9022909277376252601[17] = 0;
   out_9022909277376252601[18] = 0;
   out_9022909277376252601[19] = 0;
   out_9022909277376252601[20] = 1;
   out_9022909277376252601[21] = 0;
   out_9022909277376252601[22] = 0;
   out_9022909277376252601[23] = 0;
   out_9022909277376252601[24] = 0;
   out_9022909277376252601[25] = 0;
   out_9022909277376252601[26] = 0;
   out_9022909277376252601[27] = 0;
   out_9022909277376252601[28] = 0;
   out_9022909277376252601[29] = 0;
   out_9022909277376252601[30] = 1;
   out_9022909277376252601[31] = 0;
   out_9022909277376252601[32] = 0;
   out_9022909277376252601[33] = 0;
   out_9022909277376252601[34] = 0;
   out_9022909277376252601[35] = 0;
   out_9022909277376252601[36] = 0;
   out_9022909277376252601[37] = 0;
   out_9022909277376252601[38] = 0;
   out_9022909277376252601[39] = 0;
   out_9022909277376252601[40] = 1;
   out_9022909277376252601[41] = 0;
   out_9022909277376252601[42] = 0;
   out_9022909277376252601[43] = 0;
   out_9022909277376252601[44] = 0;
   out_9022909277376252601[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/state[1] + (-stiffness_front - stiffness_rear)*state[5]/state[4] + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/state[4]);
   out_9022909277376252601[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/pow(state[1], 2);
   out_9022909277376252601[47] = -dt*stiffness_front*state[0]/state[1];
   out_9022909277376252601[48] = -dt*stiffness_front*state[0]/state[1];
   out_9022909277376252601[49] = dt*(-(-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/pow(state[4], 2) + (-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/pow(state[4], 2) - 1)*state[6]);
   out_9022909277376252601[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/state[4] + 1;
   out_9022909277376252601[51] = dt*((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4]);
   out_9022909277376252601[52] = dt*stiffness_front*state[0]/state[1];
   out_9022909277376252601[53] = -9.8100000000000005*dt;
   out_9022909277376252601[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_9022909277376252601[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_9022909277376252601[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_9022909277376252601[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_9022909277376252601[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_9022909277376252601[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_9022909277376252601[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_9022909277376252601[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_9022909277376252601[62] = 0;
   out_9022909277376252601[63] = 0;
   out_9022909277376252601[64] = 0;
   out_9022909277376252601[65] = 0;
   out_9022909277376252601[66] = 0;
   out_9022909277376252601[67] = 0;
   out_9022909277376252601[68] = 0;
   out_9022909277376252601[69] = 0;
   out_9022909277376252601[70] = 1;
   out_9022909277376252601[71] = 0;
   out_9022909277376252601[72] = 0;
   out_9022909277376252601[73] = 0;
   out_9022909277376252601[74] = 0;
   out_9022909277376252601[75] = 0;
   out_9022909277376252601[76] = 0;
   out_9022909277376252601[77] = 0;
   out_9022909277376252601[78] = 0;
   out_9022909277376252601[79] = 0;
   out_9022909277376252601[80] = 1;
}
void h_25(double *state, double *unused, double *out_7178911009583483193) {
   out_7178911009583483193[0] = state[6];
}
void H_25(double *state, double *unused, double *out_5642153726059007232) {
   out_5642153726059007232[0] = 0;
   out_5642153726059007232[1] = 0;
   out_5642153726059007232[2] = 0;
   out_5642153726059007232[3] = 0;
   out_5642153726059007232[4] = 0;
   out_5642153726059007232[5] = 0;
   out_5642153726059007232[6] = 1;
   out_5642153726059007232[7] = 0;
   out_5642153726059007232[8] = 0;
}
void h_24(double *state, double *unused, double *out_1104138690087538503) {
   out_1104138690087538503[0] = state[4];
   out_1104138690087538503[1] = state[5];
}
void H_24(double *state, double *unused, double *out_2227862213915952772) {
   out_2227862213915952772[0] = 0;
   out_2227862213915952772[1] = 0;
   out_2227862213915952772[2] = 0;
   out_2227862213915952772[3] = 0;
   out_2227862213915952772[4] = 1;
   out_2227862213915952772[5] = 0;
   out_2227862213915952772[6] = 0;
   out_2227862213915952772[7] = 0;
   out_2227862213915952772[8] = 0;
   out_2227862213915952772[9] = 0;
   out_2227862213915952772[10] = 0;
   out_2227862213915952772[11] = 0;
   out_2227862213915952772[12] = 0;
   out_2227862213915952772[13] = 0;
   out_2227862213915952772[14] = 1;
   out_2227862213915952772[15] = 0;
   out_2227862213915952772[16] = 0;
   out_2227862213915952772[17] = 0;
}
void h_30(double *state, double *unused, double *out_408075783233132257) {
   out_408075783233132257[0] = state[4];
}
void H_30(double *state, double *unused, double *out_8160486684566255859) {
   out_8160486684566255859[0] = 0;
   out_8160486684566255859[1] = 0;
   out_8160486684566255859[2] = 0;
   out_8160486684566255859[3] = 0;
   out_8160486684566255859[4] = 1;
   out_8160486684566255859[5] = 0;
   out_8160486684566255859[6] = 0;
   out_8160486684566255859[7] = 0;
   out_8160486684566255859[8] = 0;
}
void h_26(double *state, double *unused, double *out_4593597484427713388) {
   out_4593597484427713388[0] = state[7];
}
void H_26(double *state, double *unused, double *out_1900650407184951008) {
   out_1900650407184951008[0] = 0;
   out_1900650407184951008[1] = 0;
   out_1900650407184951008[2] = 0;
   out_1900650407184951008[3] = 0;
   out_1900650407184951008[4] = 0;
   out_1900650407184951008[5] = 0;
   out_1900650407184951008[6] = 0;
   out_1900650407184951008[7] = 1;
   out_1900650407184951008[8] = 0;
}
void h_27(double *state, double *unused, double *out_6266159796465222778) {
   out_6266159796465222778[0] = state[3];
}
void H_27(double *state, double *unused, double *out_5985723372765830948) {
   out_5985723372765830948[0] = 0;
   out_5985723372765830948[1] = 0;
   out_5985723372765830948[2] = 0;
   out_5985723372765830948[3] = 1;
   out_5985723372765830948[4] = 0;
   out_5985723372765830948[5] = 0;
   out_5985723372765830948[6] = 0;
   out_5985723372765830948[7] = 0;
   out_5985723372765830948[8] = 0;
}
void h_29(double *state, double *unused, double *out_5409749050893977902) {
   out_5409749050893977902[0] = state[1];
}
void H_29(double *state, double *unused, double *out_8670718028880648043) {
   out_8670718028880648043[0] = 0;
   out_8670718028880648043[1] = 1;
   out_8670718028880648043[2] = 0;
   out_8670718028880648043[3] = 0;
   out_8670718028880648043[4] = 0;
   out_8670718028880648043[5] = 0;
   out_8670718028880648043[6] = 0;
   out_8670718028880648043[7] = 0;
   out_8670718028880648043[8] = 0;
}
void h_28(double *state, double *unused, double *out_7209669649366885213) {
   out_7209669649366885213[0] = state[0];
}
void H_28(double *state, double *unused, double *out_3588319011811117469) {
   out_3588319011811117469[0] = 1;
   out_3588319011811117469[1] = 0;
   out_3588319011811117469[2] = 0;
   out_3588319011811117469[3] = 0;
   out_3588319011811117469[4] = 0;
   out_3588319011811117469[5] = 0;
   out_3588319011811117469[6] = 0;
   out_3588319011811117469[7] = 0;
   out_3588319011811117469[8] = 0;
}
void h_31(double *state, double *unused, double *out_3504567807305395982) {
   out_3504567807305395982[0] = state[8];
}
void H_31(double *state, double *unused, double *out_1274442304951599532) {
   out_1274442304951599532[0] = 0;
   out_1274442304951599532[1] = 0;
   out_1274442304951599532[2] = 0;
   out_1274442304951599532[3] = 0;
   out_1274442304951599532[4] = 0;
   out_1274442304951599532[5] = 0;
   out_1274442304951599532[6] = 0;
   out_1274442304951599532[7] = 0;
   out_1274442304951599532[8] = 1;
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
void car_err_fun(double *nom_x, double *delta_x, double *out_4975635636005312372) {
  err_fun(nom_x, delta_x, out_4975635636005312372);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_5810940517248718795) {
  inv_err_fun(nom_x, true_x, out_5810940517248718795);
}
void car_H_mod_fun(double *state, double *out_2279184306914852573) {
  H_mod_fun(state, out_2279184306914852573);
}
void car_f_fun(double *state, double dt, double *out_2316200443245060609) {
  f_fun(state,  dt, out_2316200443245060609);
}
void car_F_fun(double *state, double dt, double *out_9022909277376252601) {
  F_fun(state,  dt, out_9022909277376252601);
}
void car_h_25(double *state, double *unused, double *out_7178911009583483193) {
  h_25(state, unused, out_7178911009583483193);
}
void car_H_25(double *state, double *unused, double *out_5642153726059007232) {
  H_25(state, unused, out_5642153726059007232);
}
void car_h_24(double *state, double *unused, double *out_1104138690087538503) {
  h_24(state, unused, out_1104138690087538503);
}
void car_H_24(double *state, double *unused, double *out_2227862213915952772) {
  H_24(state, unused, out_2227862213915952772);
}
void car_h_30(double *state, double *unused, double *out_408075783233132257) {
  h_30(state, unused, out_408075783233132257);
}
void car_H_30(double *state, double *unused, double *out_8160486684566255859) {
  H_30(state, unused, out_8160486684566255859);
}
void car_h_26(double *state, double *unused, double *out_4593597484427713388) {
  h_26(state, unused, out_4593597484427713388);
}
void car_H_26(double *state, double *unused, double *out_1900650407184951008) {
  H_26(state, unused, out_1900650407184951008);
}
void car_h_27(double *state, double *unused, double *out_6266159796465222778) {
  h_27(state, unused, out_6266159796465222778);
}
void car_H_27(double *state, double *unused, double *out_5985723372765830948) {
  H_27(state, unused, out_5985723372765830948);
}
void car_h_29(double *state, double *unused, double *out_5409749050893977902) {
  h_29(state, unused, out_5409749050893977902);
}
void car_H_29(double *state, double *unused, double *out_8670718028880648043) {
  H_29(state, unused, out_8670718028880648043);
}
void car_h_28(double *state, double *unused, double *out_7209669649366885213) {
  h_28(state, unused, out_7209669649366885213);
}
void car_H_28(double *state, double *unused, double *out_3588319011811117469) {
  H_28(state, unused, out_3588319011811117469);
}
void car_h_31(double *state, double *unused, double *out_3504567807305395982) {
  h_31(state, unused, out_3504567807305395982);
}
void car_H_31(double *state, double *unused, double *out_1274442304951599532) {
  H_31(state, unused, out_1274442304951599532);
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
