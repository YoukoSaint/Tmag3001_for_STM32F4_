#include "tmag3001_driver.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
typedef struct { int write; uint16_t addr, reg, len; uint8_t bytes[9]; HAL_StatusTypeDef status; } Call;
static Call calls[32];
static unsigned queued, consumed;
static I2C_HandleTypeDef bus;
static void reset(void) { CHECK(consumed==queued); consumed=queued=0; }
static void expect(int wr, unsigned addr, unsigned reg, const uint8_t *bytes, unsigned len, HAL_StatusTypeDef status) {
    CHECK(queued<32); Call *c=&calls[queued++]; c->write=wr; c->addr=(uint16_t)addr; c->reg=(uint16_t)reg; c->len=(uint16_t)len; c->status=status; memcpy(c->bytes,bytes,len);
}
static void byte(int wr, unsigned addr,unsigned reg,unsigned value,HAL_StatusTypeDef status) { uint8_t b=(uint8_t)value; expect(wr,addr,reg,&b,1,status); }
static HAL_StatusTypeDef transfer(int wr,I2C_HandleTypeDef *h,uint16_t addr,uint16_t reg,uint16_t size,uint8_t *data,uint16_t len,uint32_t timeout) {
    CHECK(consumed<queued); Call *c=&calls[consumed++]; CHECK(h==&bus); CHECK(c->write==wr); CHECK(c->addr==addr); CHECK(c->reg==reg); CHECK(size==I2C_MEMADD_SIZE_8BIT); CHECK(c->len==len); CHECK(timeout>0 && timeout<=20);
    if(wr) { CHECK(memcmp(c->bytes,data,len)==0); } else { memcpy(data,c->bytes,len); }
    return c->status;
}
HAL_StatusTypeDef HAL_I2C_Mem_Read(I2C_HandleTypeDef *h,uint16_t a,uint16_t r,uint16_t s,uint8_t *d,uint16_t n,uint32_t t) { return transfer(0,h,a,r,s,d,n,t); }
HAL_StatusTypeDef HAL_I2C_Mem_Write(I2C_HandleTypeDef *h,uint16_t a,uint16_t r,uint16_t s,uint8_t *d,uint16_t n,uint32_t t) { return transfer(1,h,a,r,s,d,n,t); }
void HAL_Delay(uint32_t t) { (void)t; }
static TMAG3001_Config_t config(void) { TMAG3001_Config_t c={TMAG3001_RANGE_40mT,TMAG3001_MODE_STANDBY,TMAG3001_AVG_1X,TMAG3001_CH_XYZ,1}; return c; }
static TMAG3001_Handle_t handle(void) { TMAG3001_Handle_t d={0}; d.hi2c=&bus; d.i2c_addr=0x34; return d; }
static void ids(unsigned addr,unsigned id) { byte(0,addr,0x0e,0x49,HAL_OK); byte(0,addr,0x0f,0x54,HAL_OK); byte(0,addr,0x0d,id,HAL_OK); }
static void test_init(void) {
    TMAG3001_Handle_t d; memset(&d,0xa5,sizeof d); ids(0x68,0xf3); CHECK(TMAG3001_Init(&d,&bus)==HAL_OK); CHECK(d.i2c_addr==0x34); CHECK(d.range==TMAG3001_RANGE_40mT); CHECK(d.mode==TMAG3001_MODE_STANDBY); CHECK(d.avg==TMAG3001_AVG_1X); CHECK(!d.config_valid); CHECK(d.device_config_1==0); reset();
    ids(0x6a,0); CHECK(TMAG3001_InitAtAddress(&d,&bus,0x35)==HAL_OK); CHECK(d.i2c_addr==0x35); reset();
    ids(0x68,4); CHECK(TMAG3001_Init(&d,&bus)==HAL_ERROR); CHECK(!d.config_valid); reset();
    byte(0,0x68,0x0e,0,HAL_OK); byte(0,0x68,0x0f,0x54,HAL_OK); CHECK(TMAG3001_Init(&d,&bus)==HAL_ERROR); reset();
    byte(0,0x68,0x0e,0,HAL_TIMEOUT); CHECK(TMAG3001_Init(&d,&bus)==HAL_TIMEOUT); reset();
    CHECK(TMAG3001_Init(NULL,&bus)==HAL_ERROR); CHECK(TMAG3001_Init(&d,NULL)==HAL_ERROR); CHECK(TMAG3001_InitAtAddress(&d,&bus,0x33)==HAL_ERROR); CHECK(TMAG3001_InitAtAddress(&d,&bus,0x38)==HAL_ERROR); reset();
}
static const unsigned regs[]={0,1,2,3,8};
static void queue_config(unsigned avg,unsigned range,unsigned intr,int failure,HAL_StatusTypeDef status) {
    unsigned values[]={avg<<2,0,0x70,0x80 | (range ? 3U : 0U),intr?0x86U:0U};
    for(int i=0;i<10;i++) { int n=i%5; byte(i<5,0x68,regs[n],values[n],i==failure?status:HAL_OK); if(i==failure) break; }
}
static void test_configuration(void) {
    TMAG3001_Handle_t d=handle(); TMAG3001_Config_t c=config(); queue_config(0,0,1,-1,HAL_OK); CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_OK); CHECK(d.config_valid); reset();
    byte(1,0x68,0x80,0,HAL_OK); CHECK(TMAG3001_TriggerConversion(&d)==HAL_OK); reset();
    c.avg=TMAG3001_AVG_8X; c.range=TMAG3001_RANGE_80mT; c.enable_int=0; queue_config(3,1,0,-1,HAL_OK); CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_OK); CHECK(d.device_config_1==12); CHECK(d.range==TMAG3001_RANGE_80mT); reset();
    byte(1,0x68,0x80,12,HAL_BUSY); CHECK(TMAG3001_TriggerConversion(&d)==HAL_BUSY); reset();
    for(int f=0;f<10;f++) { c=config(); d=handle(); d.range=TMAG3001_RANGE_80mT; d.avg=TMAG3001_AVG_8X; d.device_config_1=12; d.config_valid=1; queue_config(0,0,1,f,HAL_TIMEOUT); CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_TIMEOUT); CHECK(!d.config_valid); CHECK(d.range==TMAG3001_RANGE_80mT); CHECK(d.avg==TMAG3001_AVG_8X); CHECK(d.device_config_1==12); CHECK(TMAG3001_TriggerConversion(&d)==HAL_ERROR); reset(); }
    d=handle(); c=config(); for(int i=0;i<5;i++) byte(1,0x68,regs[i],(unsigned[]){0,0,0x70,0x80,0x86}[i],HAL_OK); byte(0,0x68,0,0xff,HAL_OK); CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_ERROR); CHECK(!d.config_valid); reset();
    c=config(); c.range=(TMAG3001_MagneticRange)-1; CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_ERROR);
    c=config(); c.avg=(TMAG3001_AveragingMode)6; CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_ERROR);
    c=config(); c.mode=TMAG3001_MODE_CONTINUOUS; CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_ERROR);
    c=config(); c.channels=(TMAG3001_ChannelEnable)0x71; CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_ERROR);
    c=config(); c.enable_int=2; CHECK(TMAG3001_ConfigureForAcq(&d,&c)==HAL_ERROR); reset();
}
static void test_samples(void) {
    TMAG3001_Handle_t d=handle(); d.config_valid=1; TMAG3001_Data_t out; memset(&out,0x5a,sizeof out);
    const uint8_t b[]={0x12,0x34,0x80,0,0xff,0xff,0x7f,0xff,0xa7}; expect(0,0x68,0x10,b,9,HAL_OK); CHECK(TMAG3001_ReadSample(&d,&out)==HAL_OK); CHECK(out.x_raw==-32768); CHECK(out.y_raw==-1); CHECK(out.z_raw==32767); CHECK(out.temp_raw==0x1234); CHECK(out.conv_status==0xa7); CHECK(fabsf(out.x_mT-(-32768.0f/885))<0.00001f); CHECK(fabsf(out.y_mT-(-1.0f/885))<0.00001f); CHECK(fabsf(out.z_mT-(32767.0f/885))<0.00001f); CHECK(fabsf(out.temperature_C-((4660.0f-17512)/58.2f+25))<0.0001f); reset();
    TMAG3001_Data_t before=out; expect(0,0x68,0x10,b,9,HAL_TIMEOUT); CHECK(TMAG3001_ReadSample(&d,&out)==HAL_TIMEOUT); CHECK(memcmp(&before,&out,sizeof out)==0); reset();
    expect(0,0x68,0x10,b,9,HAL_OK); CHECK(TMAG3001_ReadAll(&d,&out)==HAL_OK); reset();
    const uint8_t xyz[]={0x80,0,0xff,0xff,0x7f,0xff}; expect(0,0x68,0x12,xyz,6,HAL_OK); CHECK(TMAG3001_ReadMagData(&d,&out)==HAL_OK); CHECK(out.x_raw==-32768 && out.y_raw==-1 && out.z_raw==32767); reset();
    uint8_t status=0; byte(0,0x68,0x0d,0xf3,HAL_OK); CHECK(TMAG3001_ReadDeviceID(&d,&status)==HAL_OK); CHECK(status==0xf3); reset(); byte(0,0x68,0x1c,0x17,HAL_OK); CHECK(TMAG3001_ReadDeviceStatus(&d,&status)==HAL_OK); CHECK(status==0x17); byte(0,0x68,0x18,0x91,HAL_OK); CHECK(TMAG3001_ReadStatus(&d,&status)==HAL_OK); CHECK(status==0x91); reset();
    CHECK(isnan(TMAG3001_CountsToMagnetic(10,(TMAG3001_MagneticRange)-1))); CHECK(isnan(TMAG3001_CountsToMagnetic(10,(TMAG3001_MagneticRange)2))); CHECK(fabsf(TMAG3001_CountsToMagnetic(446,TMAG3001_RANGE_80mT)-1)<0.00001f);
}
static void test_nulls(void) {
    TMAG3001_Handle_t d=handle(), bad={0}; TMAG3001_Config_t c=config(); TMAG3001_Data_t out; uint8_t b;
    CHECK(TMAG3001_ConfigureForAcq(NULL,&c)==HAL_ERROR); CHECK(TMAG3001_ConfigureForAcq(&d,NULL)==HAL_ERROR); CHECK(TMAG3001_ConfigureForAcq(&bad,&c)==HAL_ERROR); CHECK(TMAG3001_Configure(NULL,&c)==HAL_ERROR);
    CHECK(TMAG3001_ReadSample(NULL,&out)==HAL_ERROR); CHECK(TMAG3001_ReadSample(&d,NULL)==HAL_ERROR); CHECK(TMAG3001_ReadSample(&bad,&out)==HAL_ERROR); CHECK(TMAG3001_TriggerConversion(NULL)==HAL_ERROR); CHECK(TMAG3001_TriggerConversion(&bad)==HAL_ERROR); CHECK(TMAG3001_TriggerConversion(&d)==HAL_ERROR);
    CHECK(TMAG3001_ReadRegister(NULL,0,&b)==HAL_ERROR); CHECK(TMAG3001_ReadRegister(&d,0,NULL)==HAL_ERROR); CHECK(TMAG3001_WriteRegister(&bad,0,0)==HAL_ERROR); CHECK(TMAG3001_ReadMagData(NULL,&out)==HAL_ERROR); CHECK(TMAG3001_ReadMagData(&d,NULL)==HAL_ERROR); reset();
}
static void test_legacy_and_transport(void) {
    TMAG3001_Handle_t d=handle(); TMAG3001_Config_t c;
    /* Deliberately initialize only the original four fields, as old callers do. */
    c.range=TMAG3001_RANGE_80mT; c.mode=TMAG3001_MODE_CONTINUOUS;
    c.avg=TMAG3001_AVG_2X; c.channels=TMAG3001_CH_XY;
    byte(1,0x68,0,4,HAL_OK); byte(1,0x68,1,2,HAL_OK);
    byte(1,0x68,2,0x30,HAL_OK); byte(1,0x68,3,3,HAL_OK);
    CHECK(TMAG3001_Configure(&d,&c)==HAL_OK); CHECK(!d.config_valid);
    CHECK(d.range==TMAG3001_RANGE_80mT && d.mode==TMAG3001_MODE_CONTINUOUS);
    CHECK(d.device_config_1==4); reset();
    for(unsigned status=HAL_ERROR;status<=HAL_TIMEOUT;status++) {
        c=config(); d=handle();
        queue_config(0,0,1,0,(HAL_StatusTypeDef)status);
        CHECK(TMAG3001_ConfigureForAcq(&d,&c)==(HAL_StatusTypeDef)status); reset();
        uint8_t value=0; byte(0,0x68,0x1c,0,(HAL_StatusTypeDef)status);
        CHECK(TMAG3001_ReadDeviceStatus(&d,&value)==(HAL_StatusTypeDef)status); reset();
        byte(1,0x68,2,0,(HAL_StatusTypeDef)status); d.config_valid=1;
        CHECK(TMAG3001_WriteRegister(&d,2,0)==(HAL_StatusTypeDef)status);
        CHECK(!d.config_valid); reset();
    }
    TMAG3001_Data_t out={0}; const uint8_t sample[]={0x80,0,1,0xbe,3,0x75,0xfc,0x8b,1};
    d=handle(); d.range=TMAG3001_RANGE_80mT;
    expect(0,0x68,0x10,sample,9,HAL_OK); CHECK(TMAG3001_ReadSample(&d,&out)==HAL_OK);
    CHECK(out.temp_raw==-32768); CHECK(fabsf(out.x_mT-1)<0.00001f);
    CHECK(fabsf(out.y_mT-(885.0f/446))<0.00001f); CHECK(fabsf(out.z_mT-(-885.0f/446))<0.00001f); reset();
    TMAG3001_Data_t before=out; const uint8_t xyz[]={1,2,3,4,5,6};
    expect(0,0x68,0x12,xyz,6,HAL_BUSY); CHECK(TMAG3001_ReadMagData(&d,&out)==HAL_BUSY);
    CHECK(memcmp(&out,&before,sizeof out)==0); reset();
    d.range=(TMAG3001_MagneticRange)2; CHECK(TMAG3001_ReadSample(&d,&out)==HAL_ERROR);
    CHECK(TMAG3001_ReadMagData(&d,&out)==HAL_ERROR); reset();
}
int main(void) { test_legacy_and_transport(); test_init(); test_configuration(); test_samples(); test_nulls(); printf("Driver: %u checks passed\n",checks); return 0; }
