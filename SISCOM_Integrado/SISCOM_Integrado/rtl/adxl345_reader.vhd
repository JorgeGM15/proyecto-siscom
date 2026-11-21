library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- ADXL345 de la DE10-Lite, SPI de 4 hilos, modo 3 (CPOL=1, CPHA=1).
-- Configura 100 Hz, FULL_RES, +/-16 g; lee los 6 bytes XYZ en BURST.
-- Entrega un pulso data_valid por muestra aprox. cada 20 ms (~50 Hz).
entity adxl345_reader is
    generic (
        CLK_FREQ : integer := 50000000
    );
    port (
        clk        : in  std_logic;
        rst_n      : in  std_logic;
        gs_cs_n    : out std_logic;
        gs_sclk    : out std_logic;
        gs_sdi     : out std_logic; -- FPGA MOSI hacia sensor SDI
        gs_sdo     : in  std_logic;  -- FPGA MISO desde sensor SDO
        x_raw      : out std_logic_vector(15 downto 0);
        y_raw      : out std_logic_vector(15 downto 0);
        z_raw      : out std_logic_vector(15 downto 0);
        data_valid : out std_logic
    );
end entity;

architecture rtl of adxl345_reader is
    -- SPI 1 MHz (semiperiodo de 25 ciclos a 50 MHz).
    constant HALF_TICKS : integer := CLK_FREQ / 2000000;
    constant BOOT_TICKS : integer := CLK_FREQ / 50;  -- 20 ms
    constant SAMPLE_TICKS : integer := CLK_FREQ / 50; -- 20 ms
    constant CS_GAP_TICKS : integer := CLK_FREQ / 500000; -- 2 us

    type state_t is (BOOT, SPI_START, SPI_FALL, SPI_RISE, SPI_END,
                     CS_GAP, SAMPLE_WAIT);
    signal state : state_t := BOOT;
    signal cs_i : std_logic := '1';
    signal sclk_i : std_logic := '1';
    signal sdi_i : std_logic := '0';
    signal boot_cnt : integer range 0 to BOOT_TICKS-1 := 0;
    signal sample_cnt : integer range 0 to SAMPLE_TICKS-1 := 0;
    signal gap_cnt : integer range 0 to CS_GAP_TICKS-1 := 0;
    signal half_cnt : integer range 0 to HALF_TICKS-1 := 0;
    signal txn : integer range 0 to 3 := 0;
    signal bit_index : integer range 0 to 55 := 0;
    signal total_bits : integer range 16 to 56 := 16;
    signal tx_shift : std_logic_vector(55 downto 0) := (others => '0');
    signal rx_shift : std_logic_vector(47 downto 0) := (others => '0');
    signal x_i, y_i, z_i : std_logic_vector(15 downto 0) := (others => '0');
    signal valid_i : std_logic := '0';
begin
    assert HALF_TICKS >= 2 and CS_GAP_TICKS >= 2
        report "ADXL345: reloj demasiado lento" severity failure;
    gs_cs_n <= cs_i;
    gs_sclk <= sclk_i;
    gs_sdi <= sdi_i;
    x_raw <= x_i;
    y_raw <= y_i;
    z_raw <= z_i;
    data_valid <= valid_i;

    process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                state <= BOOT;
                cs_i <= '1';
                sclk_i <= '1';
                sdi_i <= '0';
                boot_cnt <= 0;
                sample_cnt <= 0;
                gap_cnt <= 0;
                half_cnt <= 0;
                txn <= 0;
                bit_index <= 0;
                total_bits <= 16;
                tx_shift <= (others => '0');
                rx_shift <= (others => '0');
                x_i <= (others => '0');
                y_i <= (others => '0');
                z_i <= (others => '0');
                valid_i <= '0';
            else
                valid_i <= '0';
                case state is
                    when BOOT =>
                        cs_i <= '1';
                        sclk_i <= '1';
                        if boot_cnt = BOOT_TICKS - 1 then
                            boot_cnt <= 0;
                            state <= SPI_START;
                        else
                            boot_cnt <= boot_cnt + 1;
                        end if;

                    when SPI_START =>
                        cs_i <= '0';
                        sclk_i <= '1';
                        bit_index <= 0;
                        half_cnt <= 0;
                        rx_shift <= (others => '0');
                        case txn is
                            when 0 => -- BW_RATE (0x2C) = 0x0A: 100 Hz
                                tx_shift <= x"2C0A" & x"0000000000";
                                sdi_i <= '0'; -- primer bit del comando 0x2C
                                total_bits <= 16;
                            when 1 => -- DATA_FORMAT = 0x0B: FULL_RES + +/-16g, 4-wire
                                tx_shift <= x"310B" & x"0000000000";
                                sdi_i <= '0';
                                total_bits <= 16;
                            when 2 => -- POWER_CTL = 0x08: measurement mode
                                tx_shift <= x"2D08" & x"0000000000";
                                sdi_i <= '0';
                                total_bits <= 16;
                            when others => -- READ + MULTIBYTE + DATAX0 (0x32)
                                tx_shift <= x"F2" & x"000000000000";
                                sdi_i <= '1';
                                total_bits <= 56;
                        end case;
                        state <= SPI_FALL;

                    -- SPI mode 3: desplazar datos en flanco de bajada.
                    when SPI_FALL =>
                        if half_cnt = HALF_TICKS - 1 then
                            half_cnt <= 0;
                            sclk_i <= '0';
                            if bit_index > 0 then
                                sdi_i <= tx_shift(54);
                                tx_shift <= tx_shift(54 downto 0) & '0';
                            end if;
                            state <= SPI_RISE;
                        else
                            half_cnt <= half_cnt + 1;
                        end if;

                    -- Capturar MISO en flanco de subida.
                    when SPI_RISE =>
                        if half_cnt = HALF_TICKS - 1 then
                            half_cnt <= 0;
                            sclk_i <= '1';
                            if txn = 3 and bit_index >= 8 then
                                rx_shift <= rx_shift(46 downto 0) & gs_sdo;
                            end if;
                            if bit_index = total_bits - 1 then
                                state <= SPI_END;
                            else
                                bit_index <= bit_index + 1;
                                state <= SPI_FALL;
                            end if;
                        else
                            half_cnt <= half_cnt + 1;
                        end if;

                    when SPI_END =>
                        cs_i <= '1';
                        sclk_i <= '1';
                        if txn = 3 then
                            -- Registros del ADXL345: X0,X1,Y0,Y1,Z0,Z1
                            x_i <= rx_shift(39 downto 32) & rx_shift(47 downto 40);
                            y_i <= rx_shift(23 downto 16) & rx_shift(31 downto 24);
                            z_i <= rx_shift(7 downto 0) & rx_shift(15 downto 8);
                            valid_i <= '1';
                            sample_cnt <= 0;
                            state <= SAMPLE_WAIT;
                        elsif txn = 2 then
                            txn <= 3;
                            sample_cnt <= 0;
                            state <= SAMPLE_WAIT;
                        else
                            txn <= txn + 1;
                            gap_cnt <= 0;
                            state <= CS_GAP;
                        end if;

                    when CS_GAP =>
                        if gap_cnt = CS_GAP_TICKS - 1 then
                            gap_cnt <= 0;
                            state <= SPI_START;
                        else
                            gap_cnt <= gap_cnt + 1;
                        end if;

                    when SAMPLE_WAIT =>
                        if sample_cnt = SAMPLE_TICKS - 1 then
                            sample_cnt <= 0;
                            state <= SPI_START;
                        else
                            sample_cnt <= sample_cnt + 1;
                        end if;
                end case;
            end if;
        end if;
    end process;
end architecture;
