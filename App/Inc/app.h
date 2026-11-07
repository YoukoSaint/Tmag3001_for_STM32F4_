#ifndef APP_H
#define APP_H
#include "stm32f4xx_hal.h"
void App_Init(UART_HandleTypeDef *uart, I2C_HandleTypeDef *i2c);
void App_Process(void);
void App_OnSensorInt(void);
/* Board clock selection, supplied by main.c. */
uint8_t App_ClockFromHSE(void);
/* Foreground reconnect only; board may clear a stuck idle bus before scanning. */
HAL_StatusTypeDef App_BoardPrepareI2C(I2C_HandleTypeDef *i2c);
#endif
