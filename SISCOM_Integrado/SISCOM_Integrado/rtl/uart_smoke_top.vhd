library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Prueba opcional de la UART, SIN acelerometro:
-- transmite 55 AA 00 cada 500 ms, con UART_TX y UART_RX solamente.
-- Para usarla, cambia TOP_LEVEL_ENTITY en Quartus por uart_smoke_top.
entity uart_smoke_top is
    port (
        MAX10_CLK1_50 : in std_logic;
        KEY0          : in std_logic;
        UART_TX       : out std_logic;
        UART_RX       : in std_logic
    );
end entity;

architecture rtl of uart_smoke_top is
    type state_t is (ISSUE, WAIT_HIGH, WAIT_LOW, GAP);
    signal state : state_t := ISSUE;
    signal tx_data : std_logic_vector(7 downto 0) := x"55";
    signal tx_ena : std_logic := '0';
    signal tx_busy : std_logic;
    signal idx : integer range 0 to 2 := 0;
    signal wait_cycles : integer range 0 to 24999999 := 0;
begin
    SERIAL_PORT : entity work.uart_top
        generic map (CLK_FREQ => 50000000, BAUD_RATE => 115200)
        port map (
            clk => MAX10_CLK1_50, rst_n => KEY0,
            tx_data => tx_data, tx_ena => tx_ena, tx_busy => tx_busy,
            tx => UART_TX, rx => UART_RX,
            rx_data => open, rx_busy => open, rx_valid => open
        );

    process(MAX10_CLK1_50)
    begin
        if rising_edge(MAX10_CLK1_50) then
            if KEY0 = '0' then
                state <= ISSUE;
                tx_ena <= '0';
                tx_data <= x"55";
                idx <= 0;
                wait_cycles <= 0;
            else
                tx_ena <= '0';
                case state is
                    when ISSUE =>
                        if tx_busy = '0' then
                            case idx is
                                when 0 => tx_data <= x"55";
                                when 1 => tx_data <= x"AA";
                                when others => tx_data <= x"00";
                            end case;
                            tx_ena <= '1';
                            state <= WAIT_HIGH;
                        end if;
                    when WAIT_HIGH =>
                        if tx_busy = '1' then
                            state <= WAIT_LOW;
                        end if;
                    when WAIT_LOW =>
                        if tx_busy = '0' then
                            if idx = 2 then
                                idx <= 0;
                                wait_cycles <= 0;
                                state <= GAP;
                            else
                                idx <= idx + 1;
                                state <= ISSUE;
                            end if;
                        end if;
                    when GAP =>
                        if wait_cycles = 24999999 then
                            wait_cycles <= 0;
                            state <= ISSUE;
                        else
                            wait_cycles <= wait_cycles + 1;
                        end if;
                end case;
            end if;
        end if;
    end process;
end architecture;
