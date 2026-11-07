/**
 * @file    tmag3001_driver.h
 * @brief   TMAG3001 3D Hall Effect Sensor Driver for STM32
 * @details Based on Texas Instruments TMAG3001 Datasheet (ZHCSR44C / SLYS053)
 * @date    2026-04-09
 */

#ifndef TMAG3001_DRIVER_H
#define TMAG3001_DRIVER_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"

/* ======================== Device Information ======================== */
#define TMAG3001_I2C_ADDR_7BIT      0x34    // ADDR=GND, 7-bit address
#define TMAG3001_MANUF_ID_LSB_VAL   0x49    // Manufacturer ID LSB ('I')
#define TMAG3001_MANUF_ID_MSB_VAL   0x54    // Manufacturer ID MSB ('T')

/* ======================== Register Map (Datasheet Section 7.1) ======================== */
/* Configuration Registers (R/W, 8-bit each) */
#define TMAG3001_REG_DEVICE_CONFIG_1    0x00    // CRC, MAG_Tempco, Conv_AVG, I2C_RD
#define TMAG3001_REG_DEVICE_CONFIG_2    0x01    // THR_HYST, LP_LN, Trigger, Operating_Mode
#define TMAG3001_REG_SENSOR_CONFIG_1    0x02    // MAG_CH_EN, SLEEPTIME
#define TMAG3001_REG_SENSOR_CONFIG_2    0x03    // T_Rate, Range, Angle_EN, etc.
#define TMAG3001_REG_THR_CONFIG_1       0x04    // Threshold1
#define TMAG3001_REG_THR_CONFIG_2       0x05    // Threshold2
#define TMAG3001_REG_THR_CONFIG_3       0x06    // Threshold3
#define TMAG3001_REG_SENSOR_CONFIG_3    0x07    // WOC_SEL, THR_SEL, Angle_HYS
#define TMAG3001_REG_INT_CONFIG_1       0x08    // INT configuration
#define TMAG3001_REG_SENSOR_CONFIG_4    0x09    // Gain_Config / X_THR_HI
#define TMAG3001_REG_SENSOR_CONFIG_5    0x0A    // Offset1 / Y_THR_HI
#define TMAG3001_REG_SENSOR_CONFIG_6    0x0B    // Offset2 / Z_THR_HI
#define TMAG3001_REG_I2C_ADDRESS        0x0C    // I2C address register

/* Read-Only Registers */
#define TMAG3001_REG_DEVICE_ID          0x0D    // Device die ID
#define TMAG3001_REG_MANUF_ID_LSB       0x0E    // Manufacturer ID LSB (0x49)
#define TMAG3001_REG_MANUF_ID_MSB       0x0F    // Manufacturer ID MSB (0x54)

/* Result Registers (Read Only, 16-bit values in MSB+LSB pairs) */
#define TMAG3001_REG_T_RESULT_MSB       0x10    // Temperature result MSB
#define TMAG3001_REG_T_RESULT_LSB       0x11    // Temperature result LSB
#define TMAG3001_REG_X_RESULT_MSB       0x12    // X-axis result MSB
#define TMAG3001_REG_X_RESULT_LSB       0x13    // X-axis result LSB
#define TMAG3001_REG_Y_RESULT_MSB       0x14    // Y-axis result MSB
#define TMAG3001_REG_Y_RESULT_LSB       0x15    // Y-axis result LSB
#define TMAG3001_REG_Z_RESULT_MSB       0x16    // Z-axis result MSB
#define TMAG3001_REG_Z_RESULT_LSB       0x17    // Z-axis result LSB
#define TMAG3001_REG_CONV_STATUS        0x18    // Conversion status
#define TMAG3001_REG_ANGLE_RESULT_MSB   0x19    // Angle result MSB
#define TMAG3001_REG_ANGLE_RESULT_LSB   0x1A    // Angle result LSB
#define TMAG3001_REG_MAGNITUDE_RESULT   0x1B    // Magnitude result
#define TMAG3001_REG_DEVICE_STATUS      0x1C    // Device diagnostic status

/* ======================== Device_Config_1 (0x00) Bit Fields ======================== */
// Conv_AVG[4:2]
typedef enum {
    TMAG3001_AVG_1X  = 0,   // 10.5ksps (3-axis)
    TMAG3001_AVG_2X  = 1,   // 5.9ksps
    TMAG3001_AVG_4X  = 2,   // 3.1ksps
    TMAG3001_AVG_8X  = 3,   // 1.6ksps
    TMAG3001_AVG_16X = 4,   // 0.8ksps
    TMAG3001_AVG_32X = 5    // 0.4ksps
} TMAG3001_AveragingMode;

/* ======================== Device_Config_2 (0x01) Bit Fields ======================== */
// Operating_Mode[1:0]
typedef enum {
    TMAG3001_MODE_STANDBY    = 0,   // Standby (trigger to convert)
    TMAG3001_MODE_SLEEP      = 1,   // Sleep mode
    TMAG3001_MODE_CONTINUOUS = 2,   // Continuous measurement
    TMAG3001_MODE_WAKEUP     = 3    // Wake-up and sleep (duty cycle)
} TMAG3001_OperatingMode;

/* ======================== Sensor_Config_1 (0x02) Bit Fields ======================== */
// MAG_CH_EN[7:4]
typedef enum {
    TMAG3001_CH_OFF  = 0x00,    // All channels off
    TMAG3001_CH_X    = 0x10,    // X only
    TMAG3001_CH_Y    = 0x20,    // Y only
    TMAG3001_CH_XY   = 0x30,    // X + Y
    TMAG3001_CH_Z    = 0x40,    // Z only
    TMAG3001_CH_ZX   = 0x50,    // Z + X
    TMAG3001_CH_YZ   = 0x60,    // Y + Z
    TMAG3001_CH_XYZ  = 0x70     // X + Y + Z
} TMAG3001_ChannelEnable;

/* ======================== Sensor_Config_2 (0x03) Bit Fields ======================== */
// X_Y_Range[1], Z_Range[0] — for TMAG3001A1
typedef enum {
    TMAG3001_RANGE_40mT = 0,    // ±40 mT (A1) or ±120 mT (A2)
    TMAG3001_RANGE_80mT = 1     // ±80 mT (A1) or ±240 mT (A2)
} TMAG3001_MagneticRange;

/* ======================== Conv_Status (0x18) Bit Fields ======================== */
#define TMAG3001_CONV_STATUS_COMPLETE   (1 << 0)    // Conversion complete

/* ======================== Data Structures ======================== */

typedef struct {
    I2C_HandleTypeDef *hi2c;
    uint8_t i2c_addr;               // 7-bit I2C address
    TMAG3001_MagneticRange range;
    TMAG3001_OperatingMode mode;
    TMAG3001_AveragingMode avg;
    uint8_t device_config_1;      // Cached only after successful configuration
    uint8_t config_valid;         // Acquisition configuration verified by readback
} TMAG3001_Handle_t;

typedef struct {
    float x_mT;
    float y_mT;
    float z_mT;
    float temperature_C;
    uint8_t conv_status;
    int16_t x_raw;
    int16_t y_raw;
    int16_t z_raw;
    int16_t temp_raw;
} TMAG3001_Data_t;

typedef struct {
    TMAG3001_MagneticRange range;
    TMAG3001_OperatingMode mode;
    TMAG3001_AveragingMode avg;
    TMAG3001_ChannelEnable channels;
    uint8_t enable_int;           // ConfigureForAcq only; legacy Configure ignores this field
} TMAG3001_Config_t;

/* ======================== Function Prototypes ======================== */

HAL_StatusTypeDef TMAG3001_Init(TMAG3001_Handle_t *dev, I2C_HandleTypeDef *hi2c);
HAL_StatusTypeDef TMAG3001_Configure(TMAG3001_Handle_t *dev, TMAG3001_Config_t *config);
HAL_StatusTypeDef TMAG3001_ReadMagData(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data);
HAL_StatusTypeDef TMAG3001_ReadAll(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data);
HAL_StatusTypeDef TMAG3001_ReadStatus(TMAG3001_Handle_t *dev, uint8_t *status);

/* Acquisition: standby only, A1 ranges; configuration must pass readback. */
HAL_StatusTypeDef TMAG3001_InitAtAddress(TMAG3001_Handle_t *dev, I2C_HandleTypeDef *hi2c, uint8_t addr);
HAL_StatusTypeDef TMAG3001_ConfigureForAcq(TMAG3001_Handle_t *dev, const TMAG3001_Config_t *config);
HAL_StatusTypeDef TMAG3001_TriggerConversion(TMAG3001_Handle_t *dev);
HAL_StatusTypeDef TMAG3001_ReadSample(TMAG3001_Handle_t *dev, TMAG3001_Data_t *data);
HAL_StatusTypeDef TMAG3001_ReadDeviceStatus(TMAG3001_Handle_t *dev, uint8_t *status);

/* Low-level register access */
HAL_StatusTypeDef TMAG3001_ReadRegister(TMAG3001_Handle_t *dev, uint8_t reg, uint8_t *data);
HAL_StatusTypeDef TMAG3001_WriteRegister(TMAG3001_Handle_t *dev, uint8_t reg, uint8_t data);
HAL_StatusTypeDef TMAG3001_ReadDeviceID(TMAG3001_Handle_t *dev, uint8_t *id);

/* Conversion utilities */
float TMAG3001_CountsToMagnetic(int16_t counts, TMAG3001_MagneticRange range);
float TMAG3001_CountsToTemperature(int16_t counts);

#ifdef __cplusplus
}
#endif

#endif /* TMAG3001_DRIVER_H */
