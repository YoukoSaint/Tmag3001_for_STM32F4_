#ifndef BUS_MOCK_HAL_H
#define BUS_MOCK_HAL_H
#include <stddef.h>
#include <stdint.h>
typedef enum {HAL_OK, HAL_ERROR, HAL_BUSY, HAL_TIMEOUT} HAL_StatusTypeDef;
typedef struct {void *Instance;} I2C_HandleTypeDef;
typedef struct {int unused;} UART_HandleTypeDef;
typedef struct {uint32_t Pin, Mode, Pull, Speed;} GPIO_InitTypeDef;
typedef enum {GPIO_PIN_RESET, GPIO_PIN_SET} GPIO_PinState;
#define I2C1 ((void *)1)
#define GPIOB ((void *)2)
#define GPIO_PIN_6 64U
#define GPIO_PIN_7 128U
#define GPIO_MODE_OUTPUT_OD 1U
#define GPIO_PULLUP 1U
#define GPIO_SPEED_FREQ_LOW 0U
#define I2C_FLAG_BUSY 2U
#define RESET 0U
extern unsigned mock_busy;
#define __HAL_I2C_GET_FLAG(h, f) (mock_busy)
#define __HAL_RCC_GPIOB_CLK_ENABLE() ((void)0)
HAL_StatusTypeDef HAL_I2C_DeInit(I2C_HandleTypeDef *);
HAL_StatusTypeDef HAL_I2C_Init(I2C_HandleTypeDef *);
GPIO_PinState HAL_GPIO_ReadPin(void *, uint16_t);
void HAL_GPIO_WritePin(void *, uint16_t, GPIO_PinState);
void HAL_GPIO_Init(void *, GPIO_InitTypeDef *);
void HAL_Delay(uint32_t);
#endif
