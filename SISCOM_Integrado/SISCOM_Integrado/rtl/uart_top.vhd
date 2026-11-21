library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- UART 8N1, reloj 50 MHz y 115200 baudios por defecto.
-- Interfaz compatible con el contrato uart_top usado en la practica.
entity uart_top is
    generic (
        CLK_FREQ  : integer := 50000000;
        BAUD_RATE : integer := 115200
    );
    port (
        clk      : in  std_logic;
        rst_n    : in  std_logic;
        tx_data  : in  std_logic_vector(7 downto 0);
        tx_ena   : in  std_logic;
        tx_busy  : out std_logic;
        tx       : out std_logic;
        rx       : in  std_logic;
        rx_data  : out std_logic_vector(7 downto 0);
        rx_busy  : out std_logic;
        rx_valid : out std_logic
    );
end entity;

architecture rtl of uart_top is
    constant BIT_TICKS  : integer := CLK_FREQ / BAUD_RATE;
    constant HALF_TICKS : integer := BIT_TICKS / 2;

    type tx_state_t is (TX_IDLE, TX_START, TX_BITS, TX_STOP);
    signal tx_state : tx_state_t := TX_IDLE;
    signal tx_tick  : integer range 0 to BIT_TICKS - 1 := 0;
    signal tx_index : integer range 0 to 7 := 0;
    signal tx_byte  : std_logic_vector(7 downto 0) := (others => '0');
    signal tx_line  : std_logic := '1';
    signal tx_busy_i : std_logic := '0';

    type rx_state_t is (RX_IDLE, RX_START, RX_BITS, RX_STOP);
    signal rx_state : rx_state_t := RX_IDLE;
    signal rx_tick  : integer range 0 to BIT_TICKS - 1 := 0;
    signal rx_index : integer range 0 to 7 := 0;
    signal rx_shift : std_logic_vector(7 downto 0) := (others => '0');
    signal rx_byte  : std_logic_vector(7 downto 0) := (others => '0');
    signal rx_valid_i : std_logic := '0';
    signal rx_busy_i  : std_logic := '0';
    signal rx_meta : std_logic := '1';
    signal rx_sync : std_logic := '1';
begin
    assert BIT_TICKS >= 8 report "UART: BIT_TICKS es demasiado pequeno" severity failure;
    tx <= tx_line;
    tx_busy <= tx_busy_i;
    rx_data <= rx_byte;
    rx_busy <= rx_busy_i;
    rx_valid <= rx_valid_i;

    -- Transmision: solicitud tx_ena de un ciclo cuando tx_busy='0'.
    process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                tx_state <= TX_IDLE;
                tx_tick <= 0;
                tx_index <= 0;
                tx_byte <= (others => '0');
                tx_line <= '1';
                tx_busy_i <= '0';
            else
                case tx_state is
                    when TX_IDLE =>
                        tx_line <= '1';
                        tx_busy_i <= '0';
                        if tx_ena = '1' then
                            tx_byte <= tx_data;
                            tx_busy_i <= '1';
                            tx_line <= '0';
                            tx_tick <= 0;
                            tx_state <= TX_START;
                        end if;
                    when TX_START =>
                        if tx_tick = BIT_TICKS - 1 then
                            tx_tick <= 0;
                            tx_index <= 0;
                            tx_line <= tx_byte(0);
                            tx_state <= TX_BITS;
                        else
                            tx_tick <= tx_tick + 1;
                        end if;
                    when TX_BITS =>
                        if tx_tick = BIT_TICKS - 1 then
                            tx_tick <= 0;
                            if tx_index = 7 then
                                tx_line <= '1';
                                tx_state <= TX_STOP;
                            else
                                tx_index <= tx_index + 1;
                                tx_line <= tx_byte(tx_index + 1);
                            end if;
                        else
                            tx_tick <= tx_tick + 1;
                        end if;
                    when TX_STOP =>
                        if tx_tick = BIT_TICKS - 1 then
                            tx_tick <= 0;
                            tx_busy_i <= '0';
                            tx_state <= TX_IDLE;
                        else
                            tx_tick <= tx_tick + 1;
                        end if;
                end case;
            end if;
        end if;
    end process;

    -- Recepcion con sincronizador de dos FF y validacion del bit STOP.
    process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                rx_meta <= '1';
                rx_sync <= '1';
                rx_state <= RX_IDLE;
                rx_tick <= 0;
                rx_index <= 0;
                rx_shift <= (others => '0');
                rx_byte <= (others => '0');
                rx_busy_i <= '0';
                rx_valid_i <= '0';
            else
                rx_meta <= rx;
                rx_sync <= rx_meta;
                rx_valid_i <= '0';
                case rx_state is
                    when RX_IDLE =>
                        rx_busy_i <= '0';
                        if rx_sync = '0' then
                            rx_busy_i <= '1';
                            rx_tick <= HALF_TICKS - 1;
                            rx_state <= RX_START;
                        end if;
                    when RX_START =>
                        if rx_tick = 0 then
                            if rx_sync = '0' then
                                rx_tick <= BIT_TICKS - 1;
                                rx_index <= 0;
                                rx_state <= RX_BITS;
                            else
                                rx_state <= RX_IDLE;
                            end if;
                        else
                            rx_tick <= rx_tick - 1;
                        end if;
                    when RX_BITS =>
                        if rx_tick = 0 then
                            rx_shift(rx_index) <= rx_sync;
                            rx_tick <= BIT_TICKS - 1;
                            if rx_index = 7 then
                                rx_state <= RX_STOP;
                            else
                                rx_index <= rx_index + 1;
                            end if;
                        else
                            rx_tick <= rx_tick - 1;
                        end if;
                    when RX_STOP =>
                        if rx_tick = 0 then
                            if rx_sync = '1' then
                                rx_byte <= rx_shift;
                                rx_valid_i <= '1';
                            end if;
                            rx_busy_i <= '0';
                            rx_state <= RX_IDLE;
                        else
                            rx_tick <= rx_tick - 1;
                        end if;
                end case;
            end if;
        end if;
    end process;
end architecture;
