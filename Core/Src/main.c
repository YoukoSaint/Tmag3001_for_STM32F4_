/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "tmag3001_driver.h"
#include "st7789.h"
#include <stdio.h>
#include <string.h>
#include <math.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
void USART1_SendString(const char *str);
static void LCD_ShowMagData(const TMAG3001_Data_t *d);
static void LCD_ShowBootScreen(void);
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
I2C_HandleTypeDef hi2c1;

SPI_HandleTypeDef hspi1;
DMA_HandleTypeDef hdma_spi1_tx;

TIM_HandleTypeDef htim2;

UART_HandleTypeDef huart1;
DMA_HandleTypeDef hdma_usart1_rx;
DMA_HandleTypeDef hdma_usart1_tx;

/* USER CODE BEGIN PV */
TMAG3001_Handle_t tmag3001;
TMAG3001_Data_t   sensorData;
TMAG3001_Config_t magCfg;
volatile uint8_t  dataReady = 0;
volatile uint8_t  lcd_busy  = 0;

/* FPS counter: count LCD frames, update display every 1000 ms */
static uint32_t fps_frames  = 0;
static uint32_t fps_last_ms = 0;
static uint32_t fps_value   = 0;

/* UART interrupt-mode TX: non-blocking, CPU can do LCD in parallel */
static char      uart_tx_buf[100];
static volatile uint8_t uart_tx_busy = 0;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
static void MX_I2C1_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_TIM2_Init(void);
static void MX_SPI1_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  HAL_StatusTypeDef status;
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_I2C1_Init();
  MX_USART1_UART_Init();
  MX_TIM2_Init();
  MX_SPI1_Init();
  /* USER CODE BEGIN 2 */
  USART1_SendString("\r\n========================================\r\n");
  USART1_SendString("TMAG3001 + ST7789 Demo (HAL, DMA)\r\n");
  USART1_SendString("========================================\r\n\r\n");

  /* ---- I2C bus scan: find TMAG3001's actual 7-bit address ---- */
  USART1_SendString("I2C1 scan (0x03..0x77):\r\n");
  uint8_t found_addr = 0;
  for (uint8_t a = 0x03; a <= 0x77; a++) {
    if (HAL_I2C_IsDeviceReady(&hi2c1, (uint16_t)(a << 1), 1, 5) == HAL_OK) {
      char line[40];
      int n = snprintf(line, sizeof(line), "  found 0x%02X\r\n", a);
      HAL_UART_Transmit(&huart1, (uint8_t *)line, n, HAL_MAX_DELAY);
      found_addr = a;
    }
  }
  if (found_addr == 0) {
    USART1_SendString("ERROR: nothing on I2C1. Check wiring / pull-ups.\r\n");
    Error_Handler();
  }
  USART1_SendString("I2C scan done.\r\n\r\n");

  /* ---- TMAG3001 init ---- */
  USART1_SendString("Initializing TMAG3001...\r\n");
  status = TMAG3001_Init(&tmag3001, &hi2c1);
  if (status != HAL_OK)
  {
    USART1_SendString("ERROR: TMAG3001 init failed! (manuf ID mismatch?)\r\n");
    Error_Handler();
  }
  /* Override address with what we actually found on the bus */
  tmag3001.i2c_addr = found_addr;
  {
    char line[40];
    int n = snprintf(line, sizeof(line), "Using TMAG3001 @ 0x%02X (7-bit)\r\n", found_addr);
    HAL_UART_Transmit(&huart1, (uint8_t *)line, n, HAL_MAX_DELAY);
  }
  USART1_SendString("TMAG3001 init OK!\r\n");

  /* Configure: continuous mode, XYZ channels, 4x averaging, ±40 mT range */
  magCfg.range    = TMAG3001_RANGE_40mT;
  magCfg.mode     = TMAG3001_MODE_CONTINUOUS;
  magCfg.avg      = TMAG3001_AVG_4X;
  magCfg.channels = TMAG3001_CH_XYZ;
  status = TMAG3001_Configure(&tmag3001, &magCfg);
  if (status != HAL_OK)
  {
    USART1_SendString("ERROR: TMAG3001 configure failed!\r\n");
    Error_Handler();
  }
  USART1_SendString("TMAG3001 configured OK!\r\n\r\n");

  /* ---- LCD init ---- */
  USART1_SendString("Initializing ST7789...\r\n");
  ST7789_Init();

  /* Step 1: full-screen BLUE. Stays on screen until next paint. */
  USART1_SendString("  paint BLUE...\r\n");
  ST7789_Fill_Color(BLUE);
  USART1_SendString("  BLUE OK\r\n");
  HAL_Delay(500);
  /* Step 2: full-screen WHITE (was our working baseline). */
  USART1_SendString("  paint WHITE...\r\n");
  ST7789_Fill_Color(WHITE);
  USART1_SendString("  WHITE OK\r\n");
  HAL_Delay(500);
  /* Step 3: real boot screen + data. */
  LCD_ShowBootScreen();
  USART1_SendString("ST7789 init OK!\r\n\r\n");
  HAL_Delay(1000);
  /* Start timer interrupt for periodic sampling */
  HAL_TIM_Base_Start_IT(&htim2);

  USART1_SendString("Starting measurement...\r\n\r\n");
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    /* Check if data is ready */
    if (1)
    {
      dataReady = 0;

      /* Read sensor data using HAL I2C */
      status = TMAG3001_ReadAll(&tmag3001, &sensorData);

      if (status == HAL_OK)
      {
        /* Send data via USART using interrupt (non-blocking).
         * Skip if previous transfer still in flight — UART at 115200
         * can easily keep up with 50+ Hz of ~40-byte lines. */
        if (!uart_tx_busy)
        {
          int len = snprintf(uart_tx_buf, sizeof(uart_tx_buf),
                         "X:%.2f Y:%.2f Z:%.2f T:%.1fC\r\n",
                         sensorData.x_mT,
                         sensorData.y_mT,
                         sensorData.z_mT,
                         sensorData.temperature_C);
          uart_tx_busy = 1;
          HAL_UART_Transmit_IT(&huart1, (uint8_t *)uart_tx_buf, len);
        }

        /* Refresh on-screen data (only if previous DMA transfer finished) */
        if (!lcd_busy)
        {
          LCD_ShowMagData(&sensorData);
        }

        /* FPS: count this frame; if 1 s has elapsed, refresh the on-screen
         * fps readout (drawn over the top-right corner) and the serial log. */
        fps_frames++;
        {
          uint32_t now = HAL_GetTick();
          if (now - fps_last_ms >= 1000) {
            fps_value   = fps_frames * 1000 / (now - fps_last_ms);
            fps_frames  = 0;
            fps_last_ms = now;
            if (!uart_tx_busy)
            {
              int fps_n = snprintf(uart_tx_buf, sizeof(uart_tx_buf), "FPS:%lu\r\n", fps_value);
              uart_tx_busy = 1;
              HAL_UART_Transmit_IT(&huart1, (uint8_t *)uart_tx_buf, fps_n);
            }
          }
        }
      }
      else
      {
        USART1_SendString("ERROR: Read failed\r\n");
      }
    }

  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 8;
  RCC_OscInitStruct.PLL.PLLN = 96;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 4;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief I2C1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_I2C1_Init(void)
{

  /* USER CODE BEGIN I2C1_Init 0 */

  /* USER CODE END I2C1_Init 0 */

  /* USER CODE BEGIN I2C1_Init 1 */

  /* USER CODE END I2C1_Init 1 */
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 100000;
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2C1_Init 2 */

  /* USER CODE END I2C1_Init 2 */

}

/**
  * @brief SPI1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI1_Init(void)
{

  /* USER CODE BEGIN SPI1_Init 0 */

  /* USER CODE END SPI1_Init 0 */

  /* USER CODE BEGIN SPI1_Init 1 */

  /* USER CODE END SPI1_Init 1 */
  /* SPI1 parameter configuration*/
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_HIGH;
  hspi1.Init.CLKPhase = SPI_PHASE_2EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_8;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 10;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */

  /* USER CODE END TIM2_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 9999;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 9;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
  if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim2, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */

}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * Enable DMA controller clock
  */
static void MX_DMA_Init(void)
{

  /* DMA controller clock enable */
  __HAL_RCC_DMA2_CLK_ENABLE();

  /* DMA interrupt init */
  /* DMA2_Stream2_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA2_Stream2_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream2_IRQn);
  /* DMA2_Stream3_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA2_Stream3_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream3_IRQn);
  /* DMA2_Stream7_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA2_Stream7_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream7_IRQn);

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, RST_Pin|DC_Pin|BLK_Pin|CS_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : RST_Pin DC_Pin BLK_Pin CS_Pin */
  GPIO_InitStruct.Pin = RST_Pin|DC_Pin|BLK_Pin|CS_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */
  /* Turn on the LCD backlight (BLK active high on most 1.14" panels) */
  HAL_GPIO_WritePin(BLK_GPIO_Port, BLK_Pin, GPIO_PIN_SET);
  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* ---- Boot splash: drawn once after ST7789_Init ---- */
static void LCD_ShowBootScreen(void)
{
  ST7789_Fill_Color(BLACK);
  ST7789_WriteString(2,  2, "TMAG3001",   Font_11x18, WHITE,  BLACK);
  ST7789_WriteString(2, 22, "3-Axis Mag", Font_11x18, CYAN,  BLACK);
  ST7789_DrawLine(0, 42, ST7789_WIDTH - 1, 42, BLUE);
}

/* ---- Per-tick update: draw 4 data lines + FPS. No more full-region black
 * fill — each ST7789_WriteString erases its own cell with bgcolor=BLACK.
 * This saves ~55 ms of SPI traffic per frame (the 320×129 pixel wipe). */
#define LCD_DATA_Y0   44
#define LCD_DATA_Y1   (ST7789_HEIGHT - 1)

static void LCD_ShowMagData(const TMAG3001_Data_t *d)
{
  char line[24];

  /* Mark DMA busy during the whole screen update window */
  lcd_busy = 1;

  /* X axis (green) — y=46..63 (Font_11x18 = 18 px tall) */
  snprintf(line, sizeof(line), "X%+7.2f mT", d->x_mT);
  ST7789_WriteString(2, 46, line, Font_11x18, GREEN,  BLACK);

  /* Y axis (yellow) — y=66..83 */
  snprintf(line, sizeof(line), "Y%+7.2f mT", d->y_mT);
  ST7789_WriteString(2, 66, line, Font_11x18, YELLOW, BLACK);

  /* Z axis (red) — y=86..103 */
  snprintf(line, sizeof(line), "Z%+7.2f mT", d->z_mT);
  ST7789_WriteString(2, 86, line, Font_11x18, RED,    BLACK);

  /* Temperature — y=108..125 (Font_11x18 = 18 px tall) */
  snprintf(line, sizeof(line), "T%+5.1f C", d->temperature_C);
  ST7789_WriteString(2, 108, line, Font_11x18, WHITE, BLACK);

  /* FPS readout (lower-left corner, Font_16x26) */
  snprintf(line, sizeof(line), "%2luHz", fps_value);
  ST7789_WriteString(2, ST7789_HEIGHT - 28, line, Font_16x26, CYAN, BLACK);

  lcd_busy = 0;
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM2)
  {
    dataReady = 1;
  }
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
  if (huart->Instance == USART1)
  {
    uart_tx_busy = 0;
  }
}

void USART1_SendString(const char *str)
{
  uint16_t len = 0;
  const char *ptr = str;

  /* Calculate string length */
  while (*ptr++)
  {
    len++;
  }

  /* Use HAL_UART_Transmit to send the string */
  HAL_UART_Transmit(&huart1, (uint8_t *)str, len, HAL_MAX_DELAY);
}
/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
