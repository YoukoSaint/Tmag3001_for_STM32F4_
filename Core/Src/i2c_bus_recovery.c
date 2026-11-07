#include "app.h"

/* Single-controller PB6/PB7 bus. Called only while acquisition is disarmed.
 * UM10204 3.1.16: release SDA with at most nine clocks. Open-drain outputs
 * never drive a held line high. All waits are bounded; retry belongs to App.
 * A warm MCU reset can otherwise leave the sensor halfway through a read. */
HAL_StatusTypeDef App_BoardPrepareI2C(I2C_HandleTypeDef *i2c)
{
    GPIO_InitTypeDef pins = {0};
    HAL_StatusTypeDef result = HAL_OK;
    if (i2c == NULL || i2c->Instance != I2C1) return HAL_ERROR;
    if (__HAL_I2C_GET_FLAG(i2c, I2C_FLAG_BUSY) == RESET &&
        HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_6) == GPIO_PIN_SET &&
        HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_7) == GPIO_PIN_SET)
        return HAL_OK;
    if (HAL_I2C_DeInit(i2c) != HAL_OK) return HAL_ERROR;
    __HAL_RCC_GPIOB_CLK_ENABLE();
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6 | GPIO_PIN_7, GPIO_PIN_SET);
    pins.Pin = GPIO_PIN_6 | GPIO_PIN_7;
    pins.Mode = GPIO_MODE_OUTPUT_OD;
    pins.Pull = GPIO_PULLUP;
    pins.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &pins);
    HAL_Delay(1U);
    if (HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_6) == GPIO_PIN_RESET) {
        result = HAL_TIMEOUT;
    } else {
        for (unsigned pulse = 0; pulse < 9U &&
             HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_7) == GPIO_PIN_RESET; ++pulse) {
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_RESET);
            HAL_Delay(1U);
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_SET);
            HAL_Delay(1U);
            if (HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_6) == GPIO_PIN_RESET) {
                result = HAL_TIMEOUT;
                break;
            }
        }
        if (result == HAL_OK) {
            /* STOP: SDA rises while SCL is high, after a defined low phase. */
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_RESET);
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_RESET);
            HAL_Delay(1U);
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_SET);
            HAL_Delay(1U);
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, GPIO_PIN_SET);
            HAL_Delay(1U);
            if (HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_6) == GPIO_PIN_RESET ||
                HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_7) == GPIO_PIN_RESET)
                result = HAL_TIMEOUT;
        }
    }
    /* Always release our outputs and restore peripheral pin mux, even on failure. */
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6 | GPIO_PIN_7, GPIO_PIN_SET);
    if (HAL_I2C_Init(i2c) != HAL_OK) return HAL_ERROR;
    return result;
}
