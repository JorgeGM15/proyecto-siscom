library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Sistema SISCOM: envia muestras XYZ sin interpretacion a la PC.
-- Dos pines UART: TX y RX; RX reconoce S (start), P (pause), R (reset seq).
-- Trama de 12 bytes:
-- AA 55 | seq_u16 little endian | X_i16 LE | Y_i16 LE | Z_i16 LE | CRC16 LE
-- CRC16/CCITT-FALSE sobre los bytes 2..9 (init FFFF, poly 1021).
entity siscom_top is
    port (
        MAX10_CLK1_50 : in std_logic;
        KEY0          : in std_logic;
        UART_TX       : out std_logic;
        UART_RX       : in std_logic;
        GSENSOR_CS_N  : out std_logic;
        GSENSOR_SCLK  : out std_logic;
        GSENSOR_SDI   : out std_logic;
        GSENSOR_SDO   : in std_logic
    );
end entity;

architecture rtl of siscom_top is
    type frame_t is array (0 to 11) of std_logic_vector(7 downto 0);
    function crc_frame(p : frame_t) return std_logic_vector is
        variable crc : unsigned(15 downto 0) := x"FFFF";
    begin
        for i in 2 to 9 loop
            crc := crc xor (resize(unsigned(p(i)), 16) sll 8);
            for k in 0 to 7 loop
                if crc(15) = '1' then
                    crc := (crc sll 1) xor to_unsigned(16#1021#, 16);
                else
                    crc := crc sll 1;
                end if;
            end loop;
        end loop;
        return std_logic_vector(crc);
    end function;

    signal x_raw, y_raw, z_raw : std_logic_vector(15 downto 0);
    signal sample_valid : std_logic;
    signal tx_byte : std_logic_vector(7 downto 0) := (others => '0');
    signal tx_ena : std_logic := '0';
    signal tx_busy : std_logic;
    signal rx_byte : std_logic_vector(7 downto 0);
    signal rx_valid : std_logic;
    signal stream_on : std_logic := '1';
    signal sequence : unsigned(15 downto 0) := (others => '0');
    signal packet : frame_t := (others => (others => '0'));
    signal byte_idx : integer range 0 to 11 := 0;
    type send_state_t is (READY, SEND_BYTE, WAIT_BUSY, WAIT_IDLE);
    signal send_state : send_state_t := READY;
begin
    SENSOR : entity work.adxl345_reader
        generic map (CLK_FREQ => 50000000)
        port map (
            clk => MAX10_CLK1_50,
            rst_n => KEY0,
            gs_cs_n => GSENSOR_CS_N,
            gs_sclk => GSENSOR_SCLK,
            gs_sdi => GSENSOR_SDI,
            gs_sdo => GSENSOR_SDO,
            x_raw => x_raw,
            y_raw => y_raw,
            z_raw => z_raw,
            data_valid => sample_valid
        );

    SERIAL_PORT : entity work.uart_top
        generic map (
            CLK_FREQ => 50000000,
            BAUD_RATE => 115200
        )
        port map (
            clk => MAX10_CLK1_50,
            rst_n => KEY0,
            tx_data => tx_byte,
            tx_ena => tx_ena,
            tx_busy => tx_busy,
            tx => UART_TX,
            rx => UART_RX,
            rx_data => rx_byte,
            rx_busy => open,
            rx_valid => rx_valid
        );

    process(MAX10_CLK1_50)
        variable p : frame_t;
        variable c : std_logic_vector(15 downto 0);
    begin
        if rising_edge(MAX10_CLK1_50) then
            if KEY0 = '0' then
                send_state <= READY;
                packet <= (others => (others => '0'));
                byte_idx <= 0;
                sequence <= (others => '0');
                tx_ena <= '0';
                tx_byte <= (others => '0');
                stream_on <= '1';
            else
                tx_ena <= '0';

                -- Un byte RX controla el envio; procesamiento de datos en Python.
                if rx_valid = '1' then
                    case rx_byte is
                        when x"53" => stream_on <= '1'; -- 'S'
                        when x"50" => stream_on <= '0'; -- 'P'
                        when x"52" => sequence <= (others => '0'); -- 'R'
                        when others => null;
                    end case;
                end if;

                case send_state is
                    when READY =>
                        if sample_valid = '1' and stream_on = '1' then
                            p(0) := x"AA";
                            p(1) := x"55";
                            p(2) := std_logic_vector(sequence(7 downto 0));
                            p(3) := std_logic_vector(sequence(15 downto 8));
                            p(4) := x_raw(7 downto 0);
                            p(5) := x_raw(15 downto 8);
                            p(6) := y_raw(7 downto 0);
                            p(7) := y_raw(15 downto 8);
                            p(8) := z_raw(7 downto 0);
                            p(9) := z_raw(15 downto 8);
                            c := crc_frame(p);
                            p(10) := c(7 downto 0);
                            p(11) := c(15 downto 8);
                            packet <= p;
                            sequence <= sequence + 1;
                            byte_idx <= 0;
                            send_state <= SEND_BYTE;
                        end if;
                    when SEND_BYTE =>
                        if tx_busy = '0' then
                            tx_byte <= packet(byte_idx);
                            tx_ena <= '1';
                            send_state <= WAIT_BUSY;
                        end if;
                    when WAIT_BUSY =>
                        if tx_busy = '1' then
                            send_state <= WAIT_IDLE;
                        end if;
                    when WAIT_IDLE =>
                        if tx_busy = '0' then
                            if byte_idx = 11 then
                                send_state <= READY;
                            else
                                byte_idx <= byte_idx + 1;
                                send_state <= SEND_BYTE;
                            end if;
                        end if;
                end case;
            end if;
        end if;
    end process;
end architecture;
