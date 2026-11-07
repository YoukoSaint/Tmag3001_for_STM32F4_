/* Reuse the bounded application mock fixture, excluding its IRQ-only tests. */
#define APP_POLL_TEST
#include "test_app.c"

static void test_ready_poll(void)
{
    for(unsigned clock=0;clock<2;clock++) {
        reset(1);hse=(uint8_t)clock;boot();
        CHECK_EQ_U8(last_status()[7],100);
        CHECK_EQ_U16(((unsigned)last_status()[5]<<8)|last_status()[6],885);
        CHECK_EQ_U8(last_status()[4],TMAG_FLAG_SENSOR_READY|TMAG_FLAG_CFG_OK|
                    (clock ? TMAG_FLAG_CLK_SRC_HSE : 0));
        HAL_UART_ErrorCallback(&other);
        App_OnSensorInt();process();drain();
        CHECK_EQ_U8(reads,0);CHECK_EQ_U8(polls,0);
        auto_irq=1;step(APP_SAMPLE_PERIOD_MS);
        App_OnSensorInt();process();drain();
        CHECK_EQ_U8(triggers,1);CHECK_EQ_U8(reads,0);CHECK_EQ_U8(polls,0);
        step(1);
        CHECK_EQ_U8(polls,1);CHECK_EQ_U8(reads,1);CHECK_EQ_U8(count_type(0x55),1);
        const uint8_t *data=frames[frame_count-1];
        const uint8_t raw[]={0xfb,0x2e,0x09,0x29,0x80,0x00,0x44,0x64};
        CHECK(data[1]==0x55 && !memcmp(data+3,raw,8),"polling preserves signed raw wire values");
        step(APP_HEARTBEAT_MS);
        CHECK(!(last_status()[4]&(TMAG_FLAG_INT_PATH_OK|TMAG_FLAG_TRIGGER_INT)),"poll/noise never establishes INT path or INT trigger");
        CHECK_EQ_U8(ownership_failures,0);
    }
}
static void test_poll_timeout_and_interval(void)
{
    reset(1);conv=0;boot();step(APP_SAMPLE_PERIOD_MS);
    for(unsigned i=1;i<=5;i++) {
        step(1);CHECK_EQ_U8(polls,i);CHECK_EQ_U8(reads,0);
        process();drain();CHECK_EQ_U8(polls,i);
        CHECK_EQ_U8(count_error(TMAG_ERR_NO_CONV),i==5 ? 1 : 0);
    }
    step(1);CHECK_EQ_U8(polls,5);CHECK_EQ_U8(count_error(TMAG_ERR_NO_CONV),1);
    CHECK_EQ_U8(triggers,1);CHECK_EQ_U8(count_type(0x55),0);
    step(4);CHECK_EQ_U8(triggers,2);
    conv=1;step(1);CHECK_EQ_U8(count_type(0x55),1);
    reset(1);boot();step(9);CHECK_EQ_U8(polls,0);CHECK_EQ_U8(count_error(TMAG_ERR_NO_CONV),0);
}
static void test_poll_faults(void)
{
    for(unsigned phase=0;phase<3;phase++) {
        reset(1);boot();step(APP_SAMPLE_PERIOD_MS);
        if(phase==0) status_result=HAL_TIMEOUT;
        if(phase==1) sample_result=HAL_TIMEOUT;
        if(phase==2) device_result=HAL_TIMEOUT;
        step(1);
        CHECK_EQ_U8(count_error(TMAG_ERR_I2C_TIMEOUT),1);
        CHECK_EQ_U8(count_type(0x55),0);
        CHECK(!(last_status()[4]&(TMAG_FLAG_SENSOR_READY|TMAG_FLAG_CFG_OK)),"read timeout degrades readiness");
        unsigned n=triggers;step(APP_RETRY_MS-1);CHECK_EQ_U8(triggers,n);
        status_result=sample_result=device_result=HAL_OK;
        step(1);CHECK_EQ_U8(count_error(TMAG_ERR_NONE),2);
        step(APP_SAMPLE_PERIOD_MS);step(1);CHECK_EQ_U8(count_type(0x55),1);
    }
    reset(0);boot();CHECK_EQ_U8(count_error(TMAG_ERR_I2C_NACK),1);
    step(APP_HEARTBEAT_MS);CHECK_EQ_U8(count_type(0x56),2);
    CHECK_EQ_U8(count_type(0x55),0);CHECK_EQ_U8(count_error(TMAG_ERR_NONE),0);
    for(unsigned fault=0;fault<4;fault++) {
        reset(1);boot();
        if(fault==0) conv=3;
        else devstatus=(uint8_t)(0x10U|(fault==1 ? 2U : fault==2 ? 4U : 6U));
        step(APP_SAMPLE_PERIOD_MS);step(1);
        CHECK_EQ_U8(count_type(0x55),0);CHECK_EQ_U8(count_error(TMAG_ERR_SENSOR_DIAG),1);
        CHECK_EQ_U8(diagnostic_writes,0);
    }
    for(unsigned fault=0;fault<3;fault++) {
        reset(1);devstatus=(uint8_t)(0x10U|(fault==0 ? 4U : fault==1 ? 2U : 6U));
        persistent_int=1;boot();step(APP_SAMPLE_PERIOD_MS);step(1);
        CHECK_EQ_U8(count_type(0x55),0);CHECK_EQ_U8(diagnostic_writes,fault==0 ? 1 : 0);
        CHECK_EQ_U8(count_error(TMAG_ERR_SENSOR_DIAG),2);
    }
    reset(1);devstatus=0x14;conv=0xf3;fresh_conv=0x71;boot();
    CHECK_EQ_U8(diagnostic_writes,1);CHECK_EQ_U8(last_status()[9],0xf3);
    CHECK_EQ_U8(count_type(0x55),0);step(APP_SAMPLE_PERIOD_MS);step(1);
    CHECK_EQ_U8(count_type(0x55),1);CHECK_EQ_U8(diagnostic_writes,1);
    sample_result=HAL_TIMEOUT;step(APP_SAMPLE_PERIOD_MS-1);step(1);
    sample_result=HAL_OK;devstatus=0x14;step(APP_RETRY_MS);
    CHECK_EQ_U8(diagnostic_writes,1);step(APP_SAMPLE_PERIOD_MS);step(1);
    CHECK_EQ_U8(count_type(0x55),1);
}
static void test_poll_schedule(void)
{
    reset(1);boot();step(APP_SAMPLE_PERIOD_MS);read_delay=3;step(1);
    CHECK_EQ_U8(triggers,1);read_delay=0;step(6);CHECK_EQ_U8(triggers,2);
    reset(1);tick=UINT32_MAX-3;boot();step(APP_SAMPLE_PERIOD_MS);step(1);
    CHECK_EQ_U8(triggers,1);CHECK_EQ_U8(count_type(0x55),1);
    reset(1);conv=0;boot();step(APP_SAMPLE_PERIOD_MS);step(2);
    CHECK_EQ_U8(triggers,1);CHECK_EQ_U8(count_type(0x55),0);
    conv=1;step(1);CHECK_EQ_U8(count_type(0x55),1);
    step(7);CHECK_EQ_U8(triggers,2);
}
int main(void)
{
    test_ready_poll();test_poll_timeout_and_interval();test_poll_faults();test_poll_schedule();
    for(unsigned i=0;i<frame_count;i++) CHECK_EQ_U8(tmag_crc8(frames[i]+2,9),frames[i][11]);
    TEST_REPORT();
}
