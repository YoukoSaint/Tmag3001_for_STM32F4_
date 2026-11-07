#include "app.h"
#include "test_harness.h"

unsigned mock_busy;
static unsigned scl_stuck, sda_stuck, release_at, rises, delays, deinits, inits, gpio_inits;
static uint16_t outputs;
static HAL_StatusTypeDef deinit_result, init_result;
HAL_StatusTypeDef HAL_I2C_DeInit(I2C_HandleTypeDef *p)
{ CHECK(p->Instance == I2C1, "only I2C1"); ++deinits; return deinit_result; }
HAL_StatusTypeDef HAL_I2C_Init(I2C_HandleTypeDef *p)
{ CHECK(p->Instance == I2C1, "restore I2C1"); ++inits; return init_result; }
GPIO_PinState HAL_GPIO_ReadPin(void *port, uint16_t pin)
{
    CHECK(port == GPIOB, "only GPIOB");
    if (pin == GPIO_PIN_6 && scl_stuck) return GPIO_PIN_RESET;
    if (pin == GPIO_PIN_7 && sda_stuck && (!release_at || rises < release_at))
        return GPIO_PIN_RESET;
    return outputs & pin ? GPIO_PIN_SET : GPIO_PIN_RESET;
}
void HAL_GPIO_WritePin(void *port, uint16_t pins, GPIO_PinState state)
{
    CHECK(port == GPIOB, "only GPIOB outputs");
    if (state == GPIO_PIN_SET) {
        if ((pins & GPIO_PIN_6) && !(outputs & GPIO_PIN_6)) ++rises;
        outputs |= pins;
    } else outputs &= (uint16_t)~pins;
}
void HAL_GPIO_Init(void *port, GPIO_InitTypeDef *pins)
{
    CHECK(port == GPIOB && pins->Pin == (GPIO_PIN_6 | GPIO_PIN_7), "only bus pins");
    CHECK(pins->Mode == GPIO_MODE_OUTPUT_OD && pins->Pull == GPIO_PULLUP,
          "open drain recovery, never push pull");
    ++gpio_inits;
}
void HAL_Delay(uint32_t ms) { CHECK(ms == 1U, "bounded delay"); delays += ms; }
static void reset(void)
{
    mock_busy=scl_stuck=sda_stuck=release_at=rises=delays=deinits=inits=gpio_inits=0;
    outputs=GPIO_PIN_6 | GPIO_PIN_7;
    deinit_result=init_result=HAL_OK;
}
int main(void)
{
    I2C_HandleTypeDef bus={I2C1}, other={(void *)3};
    reset(); CHECK(App_BoardPrepareI2C(NULL)==HAL_ERROR,"reject null");
    CHECK(App_BoardPrepareI2C(&other)==HAL_ERROR,"reject other bus");
    CHECK(App_BoardPrepareI2C(&bus)==HAL_OK,"idle bus unchanged");
    CHECK(!deinits && !inits && !gpio_inits && !delays,"idle is passive");
    for (unsigned release=1;release<=9;++release) {
        reset();mock_busy=sda_stuck=1;release_at=release;
        CHECK(App_BoardPrepareI2C(&bus)==HAL_OK,"release stuck slave");
        CHECK(rises==release+1,"clock release then STOP");
        CHECK(inits==1 && deinits==1 && gpio_inits==1,"restore HAL/pin mux");
        CHECK(delays<=22 && outputs==(GPIO_PIN_6 | GPIO_PIN_7),"bounded and released");
    }
    reset();sda_stuck=1;release_at=3; /* Also recover with no BUSY flag. */
    CHECK(App_BoardPrepareI2C(&bus)==HAL_OK && rises==4,"low SDA alone triggers recovery");
    reset();mock_busy=1;
    CHECK(App_BoardPrepareI2C(&bus)==HAL_OK && inits==1,"clear stale peripheral BUSY");
    reset();mock_busy=sda_stuck=1;
    CHECK(App_BoardPrepareI2C(&bus)==HAL_TIMEOUT,"persistent SDA remains failure");
    CHECK(inits==1 && delays<=22 && rises==10,"bounded nine clocks plus STOP");
    reset();scl_stuck=1;
    CHECK(App_BoardPrepareI2C(&bus)==HAL_TIMEOUT,"held SCL remains failure");
    CHECK(inits==1 && rises==0 && delays==1,"no unbounded stretching wait");
    reset();mock_busy=1;deinit_result=HAL_ERROR;
    CHECK(App_BoardPrepareI2C(&bus)==HAL_ERROR && !gpio_inits,"deinit failure stops GPIO changes");
    reset();mock_busy=1;init_result=HAL_ERROR;
    CHECK(App_BoardPrepareI2C(&bus)==HAL_ERROR,"HAL restore failure propagates");
    TEST_REPORT();
}
