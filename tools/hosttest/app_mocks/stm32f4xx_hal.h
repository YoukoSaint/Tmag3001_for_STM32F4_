#ifndef APP_MOCK_HAL_H
#define APP_MOCK_HAL_H
#include <stdint.h>
typedef enum { HAL_OK=0, HAL_ERROR=1, HAL_BUSY=2, HAL_TIMEOUT=3 } HAL_StatusTypeDef;
typedef struct { int instance; } I2C_HandleTypeDef;
typedef struct { int instance; } UART_HandleTypeDef;
uint32_t HAL_GetTick(void);
HAL_StatusTypeDef HAL_I2C_IsDeviceReady(I2C_HandleTypeDef *, uint16_t, uint32_t, uint32_t);
HAL_StatusTypeDef HAL_UART_Transmit_DMA(UART_HandleTypeDef *, uint8_t *, uint16_t);
HAL_StatusTypeDef HAL_UART_AbortTransmit(UART_HandleTypeDef *);
uint32_t mock_get_primask(void);
void mock_disable_irq(void);
void mock_set_primask(uint32_t);
#define __get_PRIMASK mock_get_primask
#define __disable_irq mock_disable_irq
#define __set_PRIMASK mock_set_primask
#endif
