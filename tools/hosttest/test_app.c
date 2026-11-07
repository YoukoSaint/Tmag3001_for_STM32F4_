#include "app.h"
#include "app_config.h"
#include "tmag3001_driver.h"
#include "tmag_proto.h"
#include "test_harness.h"
#include <string.h>
#include <limits.h>
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *);
void HAL_UART_ErrorCallback(UART_HandleTypeDef *);
static UART_HandleTypeDef uart, other;
static DMA_Stream_TypeDef stream;
static DMA_HandleTypeDef dma;
static HAL_StatusTypeDef deinit_result, dma_init_result;
static unsigned deinits, dma_inits;
static I2C_HandleTypeDef i2c;
static uint32_t tick, mask, read_delay;
static uint8_t present, found_address, id_lo, id_hi, device_id, conv, devstatus, hse;
static HAL_StatusTypeDef scan_result, init_result, config_result, register_result,
    trigger_result, sample_result, status_result, device_result, start_result, abort_result;
static unsigned probes, inits, triggers, reads, polls, starts, aborts, frame_count;
static uint8_t frames[8192][12], active_copy[12];
static uint8_t *dma_ptr;
static int auto_irq, complete_on_unlock, inside_dma, ownership_failures;
uint32_t HAL_GetTick(void) { return tick; }
uint32_t mock_get_primask(void) { return mask; }
void mock_disable_irq(void) { mask=1U; }
void mock_set_primask(uint32_t m)
{
    mask=m;
    if (!m && complete_on_unlock && !inside_dma && dma_ptr) {
        complete_on_unlock=0;
        dma_ptr=NULL;
        stream.CR=0;dma.State=HAL_DMA_STATE_READY;uart.dmat=0;
        HAL_UART_TxCpltCallback(&uart);
    }
}
HAL_StatusTypeDef HAL_I2C_IsDeviceReady(I2C_HandleTypeDef *p,uint16_t a,uint32_t n,uint32_t t)
{
    CHECK(p==&i2c && n==1U && t==20U,"bounded sensor scan");
    CHECK(a>=0x68 && a<=0x6e && !(a&1),"only addresses 34..37");
    probes++;
    return present && a==((unsigned)found_address<<1) ? HAL_OK : scan_result;
}
HAL_StatusTypeDef HAL_UART_Transmit_DMA(UART_HandleTypeDef *p,uint8_t *b,uint16_t n)
{
    CHECK(p==&uart && n==12 && mask==1,"DMA start protected and correct UART");
    starts++;
    if (start_result!=HAL_OK) return start_result;
    if (dma.State!=HAL_DMA_STATE_READY) return HAL_ERROR;
    CHECK(!dma_ptr,"never start a second DMA before completion/abort");
    dma.State=HAL_DMA_STATE_BUSY;stream.CR=DMA_SxCR_EN;p->dmat=1;
    dma_ptr=b;
    memcpy(active_copy,b,12);
    if(frame_count<8192) memcpy(frames[frame_count++],b,12);
    inside_dma=1;
    inside_dma=0;
    return HAL_OK;
}
HAL_StatusTypeDef HAL_UART_AbortTransmit(UART_HandleTypeDef *p)
{
    CHECK(p==&uart,"abort passed UART");
    aborts++;
    if (!p->dmat) return HAL_OK; /* Cube clears DMAT before attempting DMA abort. */
    p->dmat=0;
    if(abort_result==HAL_TIMEOUT) dma.State=HAL_DMA_STATE_TIMEOUT;
    else if(abort_result==HAL_OK) {
        dma_ptr=NULL;stream.CR=0;dma.State=HAL_DMA_STATE_READY;
    }
    else p->dmat=1; /* Injected generic error is retryable in legacy tests. */
    return abort_result;
}
HAL_StatusTypeDef HAL_DMA_DeInit(DMA_HandleTypeDef *p)
{
    CHECK(p==&dma && !(stream.CR&DMA_SxCR_EN),"deinit only disabled TX stream");
    deinits++;
    if(deinit_result!=HAL_OK) return deinit_result;
    p->State=HAL_DMA_STATE_RESET;dma_ptr=NULL;
    return HAL_OK;
}
HAL_StatusTypeDef HAL_DMA_Init(DMA_HandleTypeDef *p)
{
    CHECK(p==&dma && !(stream.CR&DMA_SxCR_EN),"init only disabled TX stream");
    dma_inits++;
    /* HAL can return HAL_ERROR with State READY for invalid FIFO parameters. */
    p->State=HAL_DMA_STATE_READY;
    return dma_init_result;
}
uint8_t App_ClockFromHSE(void) { return hse; }
HAL_StatusTypeDef TMAG3001_InitAtAddress(TMAG3001_Handle_t *d,I2C_HandleTypeDef *p,uint8_t a)
{
    inits++;
    CHECK(p==&i2c && a==found_address,"preserve discovered address");
    *d=(TMAG3001_Handle_t){.hi2c=p,.i2c_addr=a};
    return init_result;
}
HAL_StatusTypeDef TMAG3001_ConfigureForAcq(TMAG3001_Handle_t *d,const TMAG3001_Config_t *c)
{
    CHECK(c->range==TMAG3001_RANGE_40mT && c->mode==TMAG3001_MODE_STANDBY &&
          c->avg==TMAG3001_AVG_1X && c->channels==TMAG3001_CH_XYZ && c->enable_int==1,"verified acquisition config");
    d->config_valid=(config_result==HAL_OK);
    return config_result;
}
HAL_StatusTypeDef TMAG3001_ReadRegister(TMAG3001_Handle_t *d,uint8_t r,uint8_t *v)
{
    (void)d;
    *v=r==TMAG3001_REG_MANUF_ID_LSB ? id_lo : id_hi;
    return register_result;
}
HAL_StatusTypeDef TMAG3001_ReadDeviceID(TMAG3001_Handle_t *d,uint8_t *v) { (void)d;*v=device_id;return register_result; }
HAL_StatusTypeDef TMAG3001_TriggerConversion(TMAG3001_Handle_t *d)
{
    CHECK(d->i2c_addr==found_address && mask==0,"trigger main context and found address");
    triggers++;
    if(auto_irq) App_OnSensorInt();
    return trigger_result;
}
HAL_StatusTypeDef TMAG3001_ReadSample(TMAG3001_Handle_t *d,TMAG3001_Data_t *v)
{
    (void)d;
    CHECK(mask==0,"sample outside critical section");
    reads++;
    tick+=read_delay;
    *v=(TMAG3001_Data_t){.x_raw=-1234,.y_raw=2345,.z_raw=-32768,.temp_raw=17508,.conv_status=conv};
    return sample_result;
}
HAL_StatusTypeDef TMAG3001_ReadStatus(TMAG3001_Handle_t *d,uint8_t *v) { (void)d;polls++;*v=conv;return status_result; }
HAL_StatusTypeDef TMAG3001_ReadDeviceStatus(TMAG3001_Handle_t *d,uint8_t *v) { (void)d;*v=devstatus;return device_result; }
static void complete(void)
{
    if(dma_ptr) {
        if(memcmp(dma_ptr,active_copy,12)) ownership_failures++;
        dma_ptr=NULL;
        stream.CR=0;dma.State=HAL_DMA_STATE_READY;uart.dmat=0;
        HAL_UART_TxCpltCallback(&uart);
    }
}
static void drain(void) { unsigned limit=100;while(dma_ptr && limit--) complete(); CHECK(limit>0,"bounded queue drain"); }
static void process(void) { if(dma_ptr) CHECK(memcmp(dma_ptr,active_copy,12)==0,"DMA owned slot unchanged"); App_Process(); }
static unsigned count_type(uint8_t t) { unsigned n=0;for(unsigned i=0;i<frame_count;i++) if(frames[i][1]==t)n++;return n; }
static unsigned count_error(uint8_t e) { unsigned n=0;for(unsigned i=0;i<frame_count;i++) if(frames[i][1]==0xee && frames[i][3]==e)n++;return n; }
static const uint8_t *last_status(void) { for(unsigned i=frame_count;i>0;i--) if(frames[i-1][1]==0x56)return frames[i-1];return NULL; }
static void reset(int sensor_present)
{
    tick=mask=read_delay=0;
    present=(uint8_t)sensor_present;found_address=0x36;id_lo=0x49;id_hi=0x54;device_id=0;
    conv=1;devstatus=0x11;hse=1;scan_result=HAL_ERROR;
    init_result=config_result=register_result=trigger_result=sample_result=status_result=device_result=start_result=abort_result=HAL_OK;
    probes=inits=triggers=reads=polls=starts=aborts=frame_count=0;
    dma_ptr=NULL;auto_irq=complete_on_unlock=inside_dma=ownership_failures=0;
    stream.CR=0;dma.Instance=&stream;dma.State=HAL_DMA_STATE_READY;
    uart.hdmatx=&dma;uart.dmat=0;
    deinit_result=dma_init_result=HAL_OK;deinits=dma_inits=0;
}
static void boot(void) { App_Init(&uart,&i2c);drain(); }
static void step(uint32_t ms) { tick+=ms;process();drain(); }
static void sample_irq(void) { step(APP_SAMPLE_PERIOD_MS);App_OnSensorInt();process();drain(); }
static void test_i2c_trigger_status_flags(void)
{
    /* INT signals completion; conversion starts via the I2C command. */
    for(unsigned clock=0;clock<2;clock++) {
        const uint8_t clock_flag=clock ? TMAG_FLAG_CLK_SRC_HSE : 0U;
        const uint8_t ready_flags=clock_flag | TMAG_FLAG_SENSOR_READY | TMAG_FLAG_CFG_OK;
        reset(0);hse=(uint8_t)clock;boot();
        CHECK_EQ_U8(last_status()[4],clock_flag);
        CHECK_EQ_U8(last_status()[7],100U);
        step(APP_HEARTBEAT_MS);
        CHECK_EQ_U8(last_status()[4],clock_flag);
        present=1;step(APP_RETRY_MS);
        CHECK_EQ_U8(last_status()[4],ready_flags);
        CHECK_EQ_U8(last_status()[7],100U);
        sample_irq();
        CHECK_EQ_U8(reads,1);
        CHECK_EQ_U8(last_status()[4],ready_flags | TMAG_FLAG_INT_PATH_OK);
        step(APP_SAMPLE_PERIOD_MS);step(APP_INT_TIMEOUT_MS);
        CHECK_EQ_U8(reads,2);
        CHECK_EQ_U8(polls,1);
        CHECK_EQ_U8(last_status()[4],ready_flags);
        sample_result=HAL_TIMEOUT;sample_irq();
        CHECK_EQ_U8(last_status()[4],clock_flag);
        sample_result=HAL_OK;step(APP_RETRY_MS);
        CHECK_EQ_U8(last_status()[4],ready_flags);
        sample_irq();
        CHECK_EQ_U8(last_status()[4],ready_flags | TMAG_FLAG_INT_PATH_OK);
        for(unsigned i=0;i<frame_count;i++) if(frames[i][1]==0x56) {
            CHECK(!(frames[i][4]&TMAG_FLAG_TRIGGER_INT),"I2C-triggered conversion never claims INT trigger input");
            CHECK_EQ_U8(frames[i][4]&TMAG_FLAG_CLK_SRC_HSE,clock_flag);
        }
        reset(1);hse=(uint8_t)clock;boot();
        CHECK_EQ_U8(last_status()[4],ready_flags);
        CHECK_EQ_U8(last_status()[7],100U);
    }
}
static void test_absent_and_recovery(void)
{
    reset(0);boot();
    CHECK_EQ_U8(count_error(TMAG_ERR_I2C_NACK),1);
    CHECK_EQ_U8(count_type(0x56),1);
    CHECK((last_status()[4]&0x6c)==0x40,"clock truthful in degraded state");
    CHECK_EQ_U8(probes,4);
    step(999);CHECK_EQ_U8(probes,4);CHECK_EQ_U8(count_error(6),0);
    step(1);CHECK_EQ_U8(probes,8);CHECK_EQ_U8(count_type(0x56),2);
    present=1;step(1000);CHECK_EQ_U8(inits,1);
    CHECK((last_status()[4]&0x6c)==0x4c,"recovered ready, config and HSE");
    for(unsigned i=1;i<frame_count;i++) CHECK_EQ_U8(frames[i][2],(uint8_t)(frames[i-1][2]+1));
    CHECK_EQ_U8(last_status()[7],APP_SAMPLE_RATE_HZ>255 ? APP_SAMPLE_RATE_HZ/10 : APP_SAMPLE_RATE_HZ);
}
static void test_ids_and_faults(void)
{
    reset(0);hse=0;boot();CHECK(!(last_status()[4]&0x40),"fallback HSI flag remains clear in fault");
    reset(1);init_result=HAL_ERROR;id_lo=0;boot();CHECK_EQ_U8(count_error(2),1);
    reset(1);init_result=HAL_ERROR;register_result=HAL_ERROR;boot();CHECK_EQ_U8(count_error(4),1);CHECK_EQ_U8(count_error(2),0);
    reset(1);init_result=HAL_TIMEOUT;boot();CHECK_EQ_U8(count_error(5),1);
    reset(1);init_result=HAL_ERROR;device_id=4;boot();CHECK_EQ_U8(count_error(2),1);
    reset(1);config_result=HAL_ERROR;boot();CHECK_EQ_U8(count_error(3),1);CHECK(!(last_status()[4]&0x0c),"config failure not ready");
    reset(1);config_result=HAL_TIMEOUT;boot();CHECK_EQ_U8(count_error(5),1);
    reset(1);device_result=HAL_TIMEOUT;boot();CHECK_EQ_U8(count_error(5),1);
    reset(0);scan_result=HAL_TIMEOUT;boot();CHECK_EQ_U8(count_error(5),1);
    reset(1);boot();sample_result=HAL_TIMEOUT;sample_irq();CHECK_EQ_U8(count_error(5),1);CHECK(!(last_status()[4]&0x2c),"read timeout degrades");
    unsigned old=inits;step(999);CHECK_EQ_U8(inits,old);step(1);CHECK_EQ_U8(inits,old+1);
    reset(1);boot();trigger_result=HAL_ERROR;step(APP_SAMPLE_PERIOD_MS);CHECK_EQ_U8(count_error(4),1);
    reset(1);boot();device_result=HAL_ERROR;sample_irq();CHECK_EQ_U8(count_error(4),1);CHECK_EQ_U8(count_type(0x55),0);
}
static void test_irq_and_samples(void)
{
    reset(1);boot();CHECK(!(last_status()[4]&0x20),"no assumed INT path success");
    App_OnSensorInt();process();drain();CHECK_EQ_U8(reads,0);CHECK_EQ_U8(count_error(6),0);
    auto_irq=1;step(APP_SAMPLE_PERIOD_MS);CHECK_EQ_U8(reads,0);process();drain();
    CHECK_EQ_U8(reads,1);CHECK(last_status()[4]&0x20,"IRQ during trigger is retained");
    CHECK_EQ_U8(last_status()[10],0x11);
    const uint8_t *raw=NULL;for(unsigned i=0;i<frame_count;i++)if(frames[i][1]==0x55)raw=frames[i];
    CHECK(raw && raw[3]==0xfb && raw[4]==0x2e && raw[5]==0x09 && raw[6]==0x29 && raw[7]==0x80 && raw[8]==0 && raw[9]==0x44 && raw[10]==0x64,"raw coherent sample bytes");
    App_OnSensorInt();process();drain();CHECK_EQ_U8(reads,1);
    reset(1);boot();step(APP_SAMPLE_PERIOD_MS);step(5);CHECK_EQ_U8(reads,1);CHECK_EQ_U8(polls,1);CHECK_EQ_U8(count_type(0x55),1);CHECK(!(last_status()[4]&0x20),"fallback keeps INT clear");
    reset(1);boot();conv=0;step(APP_SAMPLE_PERIOD_MS);step(5);CHECK_EQ_U8(count_error(6),1);process();drain();CHECK_EQ_U8(count_error(6),1);
    reset(1);boot();conv=3;sample_irq();CHECK_EQ_U8(count_error(7),1);CHECK_EQ_U8(count_type(0x55),0);
    reset(1);boot();devstatus=0x16;sample_irq();CHECK_EQ_U8(count_error(7),1);CHECK_EQ_U8(count_type(0x55),0);
    step(1000);CHECK_EQ_U8(last_status()[10],0x16);
    reset(1);boot();conv=2;step(APP_SAMPLE_PERIOD_MS);step(5);CHECK_EQ_U8(count_error(7),1);
    reset(1);boot();status_result=HAL_TIMEOUT;step(APP_SAMPLE_PERIOD_MS);step(5);CHECK_EQ_U8(count_error(5),1);
    reset(1);boot();conv=0;sample_irq();CHECK_EQ_U8(count_error(6),1);
    reset(1);boot();auto_irq=1;sample_irq();auto_irq=0;
    step(APP_SAMPLE_PERIOD_MS);step(5);CHECK(!(last_status()[4]&0x20),"timeout clears previously proved INT");
    sample_irq();CHECK(last_status()[4]&0x20,"later real IRQ restores INT path");
}
static void test_schedule(void)
{
    reset(1);boot();step(APP_SAMPLE_PERIOD_MS);App_OnSensorInt();read_delay=3;process();drain();
    unsigned n=triggers;read_delay=0;step(APP_SAMPLE_PERIOD_MS-3);CHECK_EQ_U8(triggers,n+1);
    reset(1);tick=UINT32_MAX-3;boot();step(APP_SAMPLE_PERIOD_MS);CHECK_EQ_U8(triggers,1);App_OnSensorInt();process();drain();CHECK_EQ_U8(reads,1);
    reset(1);boot();step(APP_SAMPLE_PERIOD_MS);step(1);CHECK_EQ_U8(triggers,1);
    reset(1);boot();step(APP_SAMPLE_PERIOD_MS);App_OnSensorInt();read_delay=3*APP_SAMPLE_PERIOD_MS;process();drain();CHECK_EQ_U8(triggers,2);CHECK_EQ_U8(reads,1);
}
static void test_dma_failures_and_overflow(void)
{
    reset(0);start_result=HAL_BUSY;App_Init(&uart,&i2c);CHECK_EQ_U8(frame_count,0);
    process();CHECK_EQ_U8(frame_count,0);start_result=HAL_OK;process();drain();CHECK_EQ_U8(frame_count,2);
    CHECK_EQ_U8(frames[0][2],0);CHECK_EQ_U8(frames[1][2],1);
    reset(0);start_result=HAL_ERROR;App_Init(&uart,&i2c);process();start_result=HAL_OK;process();drain();CHECK_EQ_U8(frame_count,2);
    reset(0);App_Init(&uart,&i2c);unsigned n=starts;HAL_UART_TxCpltCallback(&other);HAL_UART_ErrorCallback(&other);CHECK_EQ_U8(starts,n);
    HAL_UART_ErrorCallback(&uart);abort_result=HAL_ERROR;process();CHECK_EQ_U8(aborts,1);
    /* A late completion during abort recovery must not release the held slot. */
    HAL_UART_TxCpltCallback(&uart);abort_result=HAL_OK;tick+=APP_INT_TIMEOUT_MS;process();drain();CHECK_EQ_U8(frame_count,3);CHECK_EQ_U8(frames[0][2],frames[1][2]);
    reset(0);App_Init(&uart,&i2c);complete_on_unlock=1;process();drain();CHECK_EQ_U8(frame_count,2);CHECK_EQ_U8(ownership_failures,0);
    reset(0);App_Init(&uart,&i2c);
    for(unsigned i=0;i<25;i++) {tick+=1000;process();}
    CHECK_EQ_U8(frame_count,1);CHECK_EQ_U8(ownership_failures,0);
    drain();process();drain();CHECK_EQ_U8(count_error(9),1);
    CHECK_EQ_U8(ownership_failures,0);
    CHECK(last_status()[8]>0,"overflow reflected by cumulative counter");
    int gap=0;for(unsigned i=1;i<frame_count;i++)if(frames[i][2]!=(uint8_t)(frames[i-1][2]+1))gap=1;
    CHECK(gap,"queue drop visible in global sequence");
    process();drain();CHECK_EQ_U8(count_error(9),1);
    reset(0);mask=1;App_Init(&uart,&i2c);CHECK_EQ_U8(mask,1);mask=0;drain();
}
static void test_dma_timeout_recovery(void)
{
    reset(0);App_Init(&uart,&i2c);
    uint8_t *held=dma_ptr;
    HAL_UART_ErrorCallback(&other);process();CHECK_EQ_U8(aborts,0);
    HAL_UART_ErrorCallback(&uart);abort_result=HAL_TIMEOUT;process();
    CHECK(dma.State==HAL_DMA_STATE_TIMEOUT && !uart.dmat,"timeout leaves DMA poisoned with DMAT clear");
    unsigned a=aborts;
    process();CHECK_EQ_U8(aborts,a);
    unsigned n=starts;
    for(unsigned i=0;i<4;i++) {tick+=APP_INT_TIMEOUT_MS;process();HAL_UART_TxCpltCallback(&uart);}
    CHECK_EQ_U8(deinits,0);CHECK_EQ_U8(starts,n);
    CHECK(dma_ptr==held && !memcmp(held,active_copy,12),"enabled stream retains queue ownership");
    stream.CR=0;tick+=APP_INT_TIMEOUT_MS;process();drain();
    CHECK_EQ_U8(deinits,1);CHECK_EQ_U8(dma_inits,1);
    CHECK_EQ_U8(frame_count,3);CHECK_EQ_U8(frames[0][2],frames[1][2]);
    CHECK_EQ_U8(ownership_failures,0);
    reset(0);App_Init(&uart,&i2c);HAL_UART_ErrorCallback(&uart);
    abort_result=HAL_TIMEOUT;process();
    for(unsigned i=0;i<25;i++) {tick+=APP_HEARTBEAT_MS;process();}
    CHECK_EQ_U8(deinits,0);CHECK_EQ_U8(frame_count,1);
    CHECK(dma_ptr && !memcmp(dma_ptr,active_copy,12),"overflow cannot overwrite timed-out DMA slot");
    stream.CR=0;tick+=APP_INT_TIMEOUT_MS;process();drain();process();drain();
    CHECK_EQ_U8(count_error(TMAG_ERR_TX_OVERFLOW),1);
    CHECK_EQ_U8(ownership_failures,0);
    for(unsigned phase=0;phase<2;phase++) {
        reset(0);App_Init(&uart,&i2c);HAL_UART_ErrorCallback(&uart);
        abort_result=HAL_TIMEOUT;process();stream.CR=0;
        if(phase==0) deinit_result=HAL_ERROR;else dma_init_result=HAL_ERROR;
        tick+=APP_INT_TIMEOUT_MS;process();n=starts;
        CHECK_EQ_U8(frame_count,1);HAL_UART_TxCpltCallback(&uart);
        process();CHECK_EQ_U8(starts,n); /* retries are rate limited */
        deinit_result=dma_init_result=HAL_OK;tick+=APP_INT_TIMEOUT_MS;process();drain();
        CHECK_EQ_U8(frame_count,3);CHECK_EQ_U8(frames[0][2],frames[1][2]);
        CHECK_EQ_U8(ownership_failures,0);
    }
}
int main(void)
{
    test_i2c_trigger_status_flags();test_absent_and_recovery();test_ids_and_faults();test_irq_and_samples();test_schedule();test_dma_failures_and_overflow();
    test_dma_timeout_recovery();
    for(unsigned i=0;i<frame_count;i++) CHECK_EQ_U8(tmag_crc8(frames[i]+2,9),frames[i][11]);
    TEST_REPORT();
}
