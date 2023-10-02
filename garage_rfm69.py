#!/usr/bin/python3
# pylint: disable=missing-function-docstring,unused-import,redefined-outer-name
""" RFM69 utility to examine if we can send arbitrary OOK signals """

import sys
import time
from RFM69 import Radio, FREQ_433MHZ
from RFM69.registers import *
import RPi.GPIO as GPIO  # pylint: disable=consider-using-from-import

# rpi-rfm69 library needs these, but we aren't using them
NODE_ID = 0x01
NETWORK_ID = 1
RECIPIENT_ID = 0x01

# Garage signal is OOK at a measured 70bits in 50ms, therefore ~1400bps.
# In URH, we measure each symbol at 700us, therefore 1428.57 baud or bps
# 1011001011001011001011001011001011001 (37 bits, 26.4ms) [Pause 25.1ms]
GARAGE_CARRIER = 433945000
GARAGE_BITRATE = 1400  # Use 1428 here?
GARAGE_DATA = "²Ë,²È"  # In ASCII, can we send bytes in hex?

# RFM69 crystal oscillator frequency
FXOSC = 32000000
# Pi board pins (not GPIO nums)
RESET_PIN = 22
INT_PIN = 18  # DIO0
DIO1_PIN = 16
DIO2_PIN = 15

#######################################################################
#### Notes:
#######################################################################

# OokFixedThresh is the OOK noise floor RSSI(dBm), increase manually if glitch in DATA?

# Examine the FrequencyErrorIndicator,
#   - Set FeiStart = 1, if FeiDone = 1, read FeiValue.
#   - FEI(Hz) = Fstep x FeiValue
# Auto Frequency Correction
#   - AfcAutoOn = 1

#######################################################################
# Tx Startup Procedure
# If ModeReady & TxReady, indicate its 'ready to tx'
#######################################################################
# Listen Mode
# - Set ListenOn in RegOpMode to 1 while in Standby mode.
# - With ListenResolX in RegListen as 10, durations min:4.1ms, max:1.04s
#   ListenCoef = 1 to 255.
#   ... ListenResolX = '10', ListenCoef = 3, == tListenX of 12.3ms
# ! RC oscilator calibration is required! see 4.3.5
#
# Maybe use ListenCriteria (RegListen1) with SyncAddressMatch?
#
# End of cycle acions, defined by ListenEnd in RegListen3
# - 00 Stay in Rx mode, listen mode stops, must be disabled
# - 01 Stay in Rx mode until Timeout, then mode defined by Mode, listen must be disabled
# - 10 Same as above, but listen mode resumes. FIFO lost at next Rx wakeup
#
# To stop listen mode, in two single SPI accesses:
# - 1x Set RegOpMode:ListenOn=0, ListenAbort=1, set desired Mode bits (Sleep/Stdby/Rx/Tx)
# - 1x Set RegOpMode:ListenOn=0, ListenAbort=0, set desired Mode bits (Sleep/Stdby/Rx/Tx)
#######################################################################


def receiveFunction(radio):
    while True:
        # This call will block until a packet is received
        packet = radio.get_packet()
        print("Got a packet: ", end="")
        # Process packet
        print(packet)


def separator(**kwargs):
    position = kwargs.get("position", False)
    label = kwargs.get("label", False)
    col_sep = f"\x1b[38;2;0;255;161m"  # minty
    col_debug = f"\x1b[38;2;255;170;0m"  # orange
    col_reset = f"\x1b[0m"
    if position == "begin":
        if label:
            print(
                f"\n{col_sep}{'-'*4}"
                f"[{col_debug} {label} {col_sep}]"
                f"{'-'*67}{col_reset}"
            )
        else:
            print(f"{col_sep}{'-'*80}{col_reset}\n")
    if position == "end":
        print(f"{col_sep}{'-'*80}{col_reset}\n")


def register_debug(radio):
    """Define some reference sheet parsing methods"""

    def show(**kwargs):
        """params:
        reg, bits   # Show title line
        attr, value # Show associated params
        units       # optional units
        """
        reg = kwargs.get("reg", False)
        bits = kwargs.get("bits", False)
        attr = kwargs.get("attr", False)
        value = kwargs.get("value", False)
        units = kwargs.get("units", False)
        col_title = f"\x1b[38;2;0;255;161m"  # minty
        col_attr = f"\x1b[38;2;0;204;255m"  # bluey
        col_reset = f"\x1b[0m"
        # Titles
        if reg and bits:
            print(f"{col_title}{reg:27} : {col_reset}0b{bits}")
        elif reg:
            print(f"{col_title}{reg:27} : {col_reset}-")
        # Attributes
        elif attr:
            if units:
                print(f"{col_attr}  - {attr:23}   {value} {units}{col_reset}")
            else:
                print(f"{col_attr}  - {attr:23}   {value}{col_reset}")

    def _RegDataModul_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegDataModul = f"{radio._readReg(REG_DATAMODUL):08b}"
        show(reg="RegDataModul (0x2)", bits=RegDataModul)
        RegDataModul = {
            "DataMode": RegDataModul[-7:-5],
            "ModulationType": RegDataModul[-5:-3],
            "ModulationShaping": RegDataModul[-2:],
        }
        # Wretched spec sheet parsing...
        if RegDataModul["DataMode"] == "00":
            RegDataModul["DataMode"] = "Packet mode"
        if RegDataModul["DataMode"] == "10":
            RegDataModul["DataMode"] = "Continuous mode with bit synchronizer"
        if RegDataModul["DataMode"] == "11":
            RegDataModul["DataMode"] = "Continuous mode without bit synchronizer"
        show(attr="DataMode", value=RegDataModul["DataMode"])
        if RegDataModul["ModulationType"] == "00":
            RegDataModul["ModulationType"] = "FSK"
        elif RegDataModul["ModulationType"] == "01":
            RegDataModul["ModulationType"] = "OOK"
        elif RegDataModul["ModulationType"] == "11":
            RegDataModul["ModulationType"] = "mystery1?"
        elif RegDataModul["ModulationType"] == "11":
            RegDataModul["ModulationType"] = "mystery2?"
        show(attr="ModulationType", value=RegDataModul["ModulationType"])
        if RegDataModul["ModulationShaping"] == "00":
            RegDataModul["ModulationShaping"] = "No Shaping"
        elif RegDataModul["ModulationShaping"] == "01":
            RegDataModul["ModulationShaping"] = "FSK:GaussianBT=1.0, OOK:FCutoff=BR"
        elif RegDataModul["ModulationShaping"] == "10":
            RegDataModul["ModulationShaping"] = "FSK:GaussianBT=0.5, OOK:FCutoff=2*BR"
        elif RegDataModul["ModulationShaping"] == "11":
            RegDataModul["ModulationShaping"] = "FSK:GaussianBT=0.3, OOK:reserved"
        show(attr="ModulationShaping", value=RegDataModul["ModulationShaping"])

    def _RegBitrate_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        show(
            reg="RegBitrate (0x3,0x4)",
            bits=f"{radio._readReg(REG_BITRATEMSB):08b}{radio._readReg(REG_BITRATELSB):08b}",
        )
        RegBitrate = round(
            round(
                FXOSC
                / (
                    radio._readReg(REG_BITRATEMSB) << 8 | radio._readReg(REG_BITRATELSB)
                ),
            )
        )
        show(attr="Bitrate", value=RegBitrate, units="Hz")

    def _RegPacketConfig1_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegPacketConfig1 = f"{radio._readReg(REG_PACKETCONFIG1):08b}"
        show(reg="RegPacketConfig1 (0x2)", bits=RegPacketConfig1)
        RegPacketConfig1 = {
            "PacketFormat": RegPacketConfig1[-8:-7],
            "DcFree": RegPacketConfig1[-7:-5],
            "CrcOn": RegPacketConfig1[-5:-4],
            "CrcAutoClearOff": RegPacketConfig1[-4:-3],
            "AddressFiltering": RegPacketConfig1[-3:-1],
        }
        # Wretched spec sheet parsing...
        if RegPacketConfig1["PacketFormat"] == "0":
            RegPayloadLength = f"{radio._readReg(REG_PAYLOADLENGTH):08b}"
            if int(RegPayloadLength, 2) == 0:
                RegPacketConfig1["PacketFormat"] = "Unlimited length"
            else:
                RegPacketConfig1["PacketFormat"] = "Fixed length"
        elif RegPacketConfig1["PacketFormat"] == "1":
            RegPacketConfig1["PacketFormat"] = "Variable length"
        show(attr="PacketFormat", value=RegPacketConfig1["PacketFormat"])
        if RegPacketConfig1["DcFree"] == "00":
            RegPacketConfig1["DcFree"] = "None (Off)"
        elif RegPacketConfig1["DcFree"] == "01":
            RegPacketConfig1["DcFree"] = "Manchester"
        elif RegPacketConfig1["DcFree"] == "10":
            RegPacketConfig1["DcFree"] = "Whitening"
        show(attr="DcFree", value=RegPacketConfig1["DcFree"])
        if RegPacketConfig1["CrcOn"] == "0":
            RegPacketConfig1["CrcOn"] = "Off"
        elif RegPacketConfig1["CrcOn"] == "1":
            RegPacketConfig1["CrcOn"] = "On"
        show(attr="CrcOn", value=RegPacketConfig1["CrcOn"])
        if RegPacketConfig1["CrcAutoClearOff"] == "0":
            RegPacketConfig1[
                "CrcAutoClearOff"
            ] = "Clear FIFO on CRC fail restart new packet reception"
        elif RegPacketConfig1["CrcAutoClearOff"] == "1":
            RegPacketConfig1["CrcAutoClearOff"] = "Do not clear FIFO on CRC fail"
        show(attr="CrcAutoClearOff", value=RegPacketConfig1["CrcAutoClearOff"])
        if RegPacketConfig1["AddressFiltering"] == "00":
            RegPacketConfig1["AddressFiltering"] = "None (Off)"
        elif RegPacketConfig1["AddressFiltering"] == "01":
            RegPacketConfig1[
                "AddressFiltering"
            ] = "Address field must match NodeAddress"
        elif RegPacketConfig1["AddressFiltering"] == "10":
            RegPacketConfig1[
                "AddressFiltering"
            ] = "Address field must match NodeAddress or BroadcastAddress"
        show(attr="AddressFiltering", value=RegPacketConfig1["AddressFiltering"])

    def _RegPacketConfig2_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegPacketConfig2 = f"{radio._readReg(REG_PACKETCONFIG2):08b}"
        show(reg="RegPacketConfig2 (0x2)", bits=RegPacketConfig2)
        RegPacketConfig2 = {
            "InterPacketRxDelay": RegPacketConfig2[-8:-4],
            "AutoRxRestartOn": RegPacketConfig2[-2:-1],
            "AesOn": RegPacketConfig2[-1:],
        }
        # Wretched spec sheet parsing...
        if RegPacketConfig2["AesOn"] == "0":
            RegPacketConfig2["AesOn"] = "Off"
        if RegPacketConfig2["AesOn"] == "1":
            RegPacketConfig2["AesOn"] = "On"
        show(attr="AesOn", value=RegPacketConfig2["AesOn"])

    def _RegAesKey_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegAesKey = (
            f"{radio._readReg(REG_AESKEY1):08b}"
            f"{radio._readReg(REG_AESKEY2):08b}"
            f"{radio._readReg(REG_AESKEY3):08b}"
            f"{radio._readReg(REG_AESKEY4):08b}"
            f"{radio._readReg(REG_AESKEY5):08b}"
            f"{radio._readReg(REG_AESKEY6):08b}"
            f"{radio._readReg(REG_AESKEY7):08b}"
            f"{radio._readReg(REG_AESKEY8):08b}"
            f"{radio._readReg(REG_AESKEY9):08b}"
            f"{radio._readReg(REG_AESKEY10):08b}"
            f"{radio._readReg(REG_AESKEY11):08b}"
            f"{radio._readReg(REG_AESKEY12):08b}"
            f"{radio._readReg(REG_AESKEY13):08b}"
            f"{radio._readReg(REG_AESKEY14):08b}"
            f"{radio._readReg(REG_AESKEY15):08b}"
            f"{radio._readReg(REG_AESKEY16):08b}"
        )
        show(reg="RegAesKey (0x3e-0x4d)", bits=False)
        RegAesKey_hex = hex(int(RegAesKey, 2))
        show(attr="AesKey", value=f"0x{int(RegAesKey_hex,16):032x}")

    def _RegPreamble_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        show(
            reg="RegPreamble (0x2c,0x2d)",
            bits=f"{radio._readReg(REG_PREAMBLEMSB):08b}{radio._readReg(REG_PREAMBLELSB):08b}",
        )
        RegPreamble = radio._readReg(REG_PREAMBLEMSB) << 8 | radio._readReg(
            REG_PREAMBLELSB
        )
        show(attr="Preamble Length", value=RegPreamble, units="bytes")

    def _RegSyncConfig_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegSyncConfig = f"{radio._readReg(REG_SYNCCONFIG):08b}"
        show(reg="RegSyncConfig (0x2e)", bits=RegSyncConfig)
        RegSyncConfig = {
            "SyncOn": RegSyncConfig[-8:-7],
            "FifoFillCondition": RegSyncConfig[-7:-6],
            "SyncSize": RegSyncConfig[-6:-3],
            "SyncTol": RegSyncConfig[-3:],
        }
        # Wretched spec sheet parsing...
        if RegSyncConfig["SyncOn"] == "0":
            RegSyncConfig["SyncOn"] = "Off"
        elif RegSyncConfig["SyncOn"] == "1":
            RegSyncConfig["SyncOn"] = "On"
        show(attr="SyncOn", value=RegSyncConfig["SyncOn"])
        if RegSyncConfig["FifoFillCondition"] == "0":
            RegSyncConfig["FifoFillCondition"] = "If SyncAddress interrupt occurs"
        elif RegSyncConfig["FifoFillCondition"] == "1":
            RegSyncConfig["FifoFillCondition"] = "As long as FifoFillCondition is set"
        show(attr="FifoFillCondition", value=RegSyncConfig["FifoFillCondition"])
        show(
            attr="SyncSize",
            value=int(RegSyncConfig["SyncSize"], 2) + 1,
            units="bytes",
        )
        show(attr="SyncTol", value=int(RegSyncConfig["SyncTol"], 2), units="bits")

    def _RegSyncValue_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegSyncValue = (
            f"{radio._readReg(REG_SYNCVALUE1):08b}"
            f"{radio._readReg(REG_SYNCVALUE2):08b}"
            f"{radio._readReg(REG_SYNCVALUE3):08b}"
            f"{radio._readReg(REG_SYNCVALUE4):08b}"
            f"{radio._readReg(REG_SYNCVALUE5):08b}"
            f"{radio._readReg(REG_SYNCVALUE6):08b}"
            f"{radio._readReg(REG_SYNCVALUE7):08b}"
            f"{radio._readReg(REG_SYNCVALUE8):08b}"
        )
        show(reg="RegSyncValue (0x2f-0x36)", bits=False)
        RegSyncValue_hex = hex(int(RegSyncValue, 2))
        show(attr="SyncValue", value=f"0x{int(RegSyncValue_hex,16):016x}")

    def _RegPayloadLength_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegPayloadLength = f"{radio._readReg(REG_PAYLOADLENGTH):08b}"
        show(reg="RegPayloadLength (0x38)", bits=RegPayloadLength)
        RegPayloadLength = {
            "PayloadLength": RegPayloadLength[-8:],
        }
        # Wretched spec sheet parsing...
        show(attr="PayloadLength", value=int(RegPayloadLength["PayloadLength"], 2))

    def _RegFifoThresh_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegFifoThresh = f"{radio._readReg(REG_FIFOTHRESH):08b}"
        show(reg="RegFifoThresh (0x3c)", bits=RegFifoThresh)
        RegFifoThresh = {
            "TxStartCondition": RegFifoThresh[-8:-7],
            "FifoThreshold": RegFifoThresh[-7:],
        }
        # Wretched spec sheet parsing...
        if RegFifoThresh["TxStartCondition"] == "0":
            RegFifoThresh[
                "TxStartCondition"
            ] = "(0) FifoLevel (number of bytes in FIFO is FifoThreshold + 1)"
        elif RegFifoThresh["TxStartCondition"] == "1":
            RegFifoThresh[
                "TxStartCondition"
            ] = "(1) FifoNotEmpty (at least one byte in the FIFO)"
        show(attr="TxStartCondition", value=RegFifoThresh["TxStartCondition"])
        show(
            attr="FifoThreshold",
            value=int(RegFifoThresh["FifoThreshold"], 2),
            units="bytes (Used to trigger FifoLevel interrupt)",
        )

    def _RegPaLevel_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegPaLevel = f"{radio._readReg(REG_PALEVEL):08b}"
        show(reg="RegPaLevel (0x11)", bits=RegPaLevel)
        RegPaLevel = {
            "Pa0On": RegPaLevel[-8:-7],
            "Pa1On": RegPaLevel[-7:-6],
            "Pa2On": RegPaLevel[-6:-5],
            "OutputPower": RegPaLevel[-5:],
        }
        # Wretched spec sheet parsing...
        if RegPaLevel["Pa0On"] == "1":
            RegPaLevel["Pa0On"] = "Enabled"
        elif RegPaLevel["Pa0On"] == "0":
            RegPaLevel["Pa0On"] = "Disabled"
        show(attr="Pa0On", value=RegPaLevel["Pa0On"])
        if RegPaLevel["Pa1On"] == "1":
            RegPaLevel["Pa1On"] = "Enabled"
        elif RegPaLevel["Pa1On"] == "0":
            RegPaLevel["Pa1On"] = "Disabled"
        show(attr="Pa1On", value=RegPaLevel["Pa1On"])
        if RegPaLevel["Pa2On"] == "1":
            RegPaLevel["Pa2On"] = "Enabled"
        elif RegPaLevel["Pa2On"] == "0":
            RegPaLevel["Pa2On"] = "Disabled"
        show(attr="Pa2On", value=RegPaLevel["Pa2On"])
        show(attr="OutputPower", value=int(RegPaLevel["OutputPower"], 2), units="dBm")

    def _RegOcp_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegOcp = f"{radio._readReg(REG_OCP):08b}"
        show(reg="RegOcp (0x13)", bits=RegOcp)
        RegOcp = {
            "OcpOn": RegOcp[-5:-4],
            "OcpTrim": RegOcp[-4:],
        }
        # Wretched spec sheet parsing...
        if RegOcp["OcpOn"] == "1":
            RegOcp["OcpOn"] = "Enabled"
        elif RegOcp["OcpOn"] == "0":
            RegOcp["OcpOn"] = "Disabled"
        show(attr="OcpOn", value=RegOcp["OcpOn"])
        show(attr="OcpTrim", value=45 + (5 * int(RegOcp["OcpTrim"], 2)), units="mA")

    def _RegTestPa1_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegTestPa1 = f"{radio._readReg(REG_TESTPA1):08b}"
        show(reg="RegTestPa1 (0x5a)", bits=RegTestPa1)
        RegTestPa1 = {
            "Pa20dBm1": RegTestPa1[-8:],
        }
        # Wretched spec sheet parsing...
        if int(RegTestPa1["Pa20dBm1"], 2) == 0x55:
            RegTestPa1["Pa20dBm1"] = "Normal and Rx mode"
        elif int(RegTestPa1["Pa20dBm1"], 2) == 0x5D:
            RegTestPa1["Pa20dBm1"] = "+20dBm mode"
        show(attr="Pa20dBm1", value=RegTestPa1["Pa20dBm1"])

    def _RegTestPa2_parse():
        # Render as an 8-bit zero-padded string (for hacky slicing)
        RegTestPa2 = f"{radio._readReg(REG_TESTPA2):08b}"
        show(reg="RegTestPa2 (0x5c)", bits=RegTestPa2)
        RegTestPa2 = {
            "Pa20dBm2": RegTestPa2[-8:],
        }
        # Wretched spec sheet parsing...
        if int(RegTestPa2["Pa20dBm2"], 2) == 0x70:
            RegTestPa2["Pa20dBm2"] = "Normal and Rx mode"
        elif int(RegTestPa2["Pa20dBm2"], 2) == 0x7C:
            RegTestPa2["Pa20dBm2"] = "+20dBm mode"
        show(attr="Pa20dBm2", value=RegTestPa2["Pa20dBm2"])

    ####
    #### Check registers
    ####
    separator(label="CONFIG REGISTERS", position="begin")
    _RegDataModul_parse()
    _RegBitrate_parse()
    _RegPacketConfig1_parse()
    _RegPacketConfig2_parse()
    _RegAesKey_parse()
    _RegPreamble_parse()
    _RegSyncConfig_parse()
    _RegSyncValue_parse()
    _RegPayloadLength_parse()
    _RegFifoThresh_parse()
    _RegPaLevel_parse()
    _RegOcp_parse()
    _RegTestPa1_parse()
    _RegTestPa2_parse()
    # print(f"0x5A : RegTestPa1    : {hex(int(registers['0x5a'], 2))}")
    # print(f"0x5C : RegTestPa2    : {hex(int(registers['0x5c'], 2))}")
    separator(position="end")


def register_setup(radio):
    """Setup the RFM69 registers for our chosen transmission format"""
    print(f"[+] Setting frequency to {GARAGE_CARRIER}Hz")
    radio.set_frequency_in_Hz(GARAGE_CARRIER)

    print("[+] Setting radio to Packet mode, OOK modulation, with no shaping")
    RF_DATAMODUL_MODULATIONTYPE_MYSTERY1 = 0x10
    RF_DATAMODUL_MODULATIONTYPE_MYSTERY2 = 0x18
    radio._writeReg(
        REG_DATAMODUL,
        RF_DATAMODUL_DATAMODE_PACKET
        | RF_DATAMODUL_MODULATIONTYPE_OOK
        | RF_DATAMODUL_MODULATIONSHAPING_00,
    )

    print("[+] Setting fixed length packet format, disabling CRC")
    # Unlimited length packet format is selected when bit PacketFormat is
    # set to 0 (Fixed) and PayloadLength is set to 0.
    #
    # RF_PACKET1_FORMAT_FIXED
    # RF_PACKET1_FORMAT_VARIABLE
    radio._writeReg(
        REG_PACKETCONFIG1,
        RF_PACKET1_FORMAT_FIXED
        | RF_PACKET1_DCFREE_OFF
        | RF_PACKET1_CRC_OFF
        | RF_PACKET1_CRCAUTOCLEAR_ON
        | RF_PACKET1_ADRSFILTERING_OFF,
    )

    print("[+] Setting payload length")
    radio._writeReg(
        REG_PAYLOADLENGTH,
        0x00,
    )

    print("[+] Setting FIFO threshold")
    # TxStartCondition = 0 triggers at this threshold + 1,
    # so set to payloadlength - 1
    #
    # Bit 7 :
    # RF_FIFOTHRESH_TXSTART_FIFONOTEMPTY = 1 (0x80)
    # RF_FIFOTHRESH_TXSTART_FIFOTHRESH = 0 (0x00)
    radio._writeReg(
        REG_FIFOTHRESH,
        RF_FIFOTHRESH_TXSTART_FIFONOTEMPTY | 0x00,
    )

    print("[+] Disable preamble and sync word")
    radio._writeReg(REG_PREAMBLEMSB, 0x00)
    radio._writeReg(REG_PREAMBLELSB, 0x00)
    radio._writeReg(REG_SYNCCONFIG, RF_SYNC_OFF | RF_SYNC_SIZE_1)
    radio._writeReg(REG_SYNCVALUE1, 0x00)
    radio._writeReg(REG_SYNCVALUE2, 0x00)
    # disable address byte - have to edit RPi-RFM69 code

    print(f"[+] Setting bitrate to {GARAGE_BITRATE}Hz")
    # bitrate  = 32MHz(FXOSC) / bitrateMsb,bitrateLsb
    # 32MHz / wanted_bitrate = bitrateMsb,bitrateLsb
    # 1200kb/s = 32MHz / 26667 (0x682B) (0b01101000 00101011)
    # 1400kb/s = 32MHz / 22857 (0x5949) (0b01011001 01001001)
    RF_BITRATEMSB_1400 = 0x59
    RF_BITRATELSB_1400 = 0x49
    radio._writeReg(REG_BITRATEMSB, RF_BITRATEMSB_1400)
    radio._writeReg(REG_BITRATELSB, RF_BITRATELSB_1400)

    print(f"[+] Setting +20dBm power amplifier mode, disabling OCP")
    radio._writeReg(REG_TESTPA1, 0x5D)
    radio._writeReg(REG_TESTPA2, 0x7C)
    radio._writeReg(REG_OCP, 0xF)

    # print("[+] Enabling Automatic-Frequency-Correction (AFC)")
    # Improved AutomaticFrequencyCorrection (AFC) routine for
    # signals with modulation index lower than 2
    # radio._writeReg(REG_AFCFEI, RF_AFCFEI_AFCAUTO_ON)  # AFC on with each Rx mode
    # radio._writeReg(REG_AFCCTRL, 0x10)  # AfcLowBetaOn=1 (Bit 5 enabled)

    # print("[+] Enabling Digital-Automatic-Gain-Control (DAGC)")
    #   - RF_DAGC_IMPROVED_LOWBETA0 (0x30) for all other systems
    #   - RF_DAGC_IMPROVED_LOWBETA1 (0x20) for low modulation index systems
    # radio._writeReg(REG_TESTDAGC, RF_DAGC_IMPROVED_LOWBETA1)

    # print("[+] Setting channel filter bandwidth (for AFC mode)")
    # DC Cancellation (DCC) Cutoff Frequencies
    #   - 001 = 8% of RxBw
    #   - 010 = 4% of RxBw (default)
    #   - 011 = 2% of RxBw
    #   - 100 = 1% of RxBw
    #   - 101 =.5% of RxBw
    # Channel filter bandwidth (for OOK signals)
    #     RxBwMant(bin), RxBwExp(int), Bw(kHz)
    #     bits 4-5
    #   - 00b/16,        6,            3.9   (allows reception at f +/- 4kHz)
    #   - 10b/24,        5,            5.2   # Library default for OOK
    #   - 01b/20,        3,            25.0  # Library default for OOK + AFC
    #   - 10b/24,        1,            83.3  (allows reception at f +/- 100kHz)
    # NB: In OOK mode, local oscillator is offset by (0.5 * Bw), with the
    # resulting image attenuated by 30dB.
    # radio._writeReg(
    #    REG_AFCBW,
    #    RF_AFCBW_DCCFREQAFC_100 | RF_AFCBW_MANTAFC_20 | RF_AFCBW_EXPAFC_3,
    # )


with Radio(
    FREQ_433MHZ,
    NODE_ID,
    NETWORK_ID,
    isHighPower=True,
    power=100,
    verbose=True,
    autoAcknowledge=False,
    promiscuousMode=True,
    use_board_pin_numbers=True,
    interruptPin=INT_PIN,
    resetPin=RESET_PIN,
    spiBus=0,
    spiDevice=0,
) as radio:

    separator(label="RFM59 Register Setup", position="begin")
    register_setup(radio)
    CLEAR_TO_SEND = True

    if len(sys.argv) > 1:
        if sys.argv[1] == "-d":
            register_debug(radio)
        if sys.argv[1] == "-t":
            CLEAR_TO_SEND = False

    # This works, kinda, but a separate packet with 0x08 sits between the valid
    # data?!
    # GARAGE_DATA = b"\x00\x00\xb2\xcb\x2c\xb2\xc8\x00"
    # So lets use brute force and repeat the pattern within the packet itself
    GARAGE_DATA = (
        b"\x00\x00\xb2\xcb\x2c\xb2\xc8\x00\x00"
        b"\x00\x00\xb2\xcb\x2c\xb2\xc8\x00\x00"
        b"\x00\x00\xb2\xcb\x2c\xb2\xc8\x00\x00"
        b"\x00\x00\xb2\xcb\x2c\xb2\xc8\x00\x00"
        b"\x00\x00\xb2\xcb\x2c\xb2\xc8\x00\x00"
        b"\x00\x00\xb2\xcb\x2c\xb2\xc8\x00\x00"
        b"\x00\x00\xb2\xcb\x2c\xb2\xc8"
    )
    for p in range(0, 32):
        print(f"[*] Sending packets for Garage...")
        # Second packet always gets a 1 bit prefixed ?!
        # if we mangle GARAGE_DATA to trim it's leading 1 bit, maybe we'll
        # have valid data from the second packet onwards....
        # 10110010 11001011 00101100 10110010 11001 / 178 203 44 178 200 / 0xb2cb2cb2c8
        # becomes...
        # 01100101 10010110 01011001 01100101 1001  / 101 150 89 101 9   / 0x6596596509
        # radio._setMode(RF69_MODE_STANDBY)
        # while (radio._readReg(REG_IRQFLAGS1) & RF_IRQFLAGS1_MODEREADY) == 0x00:
        #    print("DEBUG: waiting modeready2")
        #    pass

        if CLEAR_TO_SEND:
            radio.send(
                False,
                GARAGE_DATA,
                attempts=1,
                require_ack=False,
            )
            time.sleep(0.008)
        else:
            print("Not really sending due to '-t'")


print("\nFinished!")
