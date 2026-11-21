# На WS: интерфейсы, на которых слушают порты работающих тест-клиентов, и адреса машины.
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -ge 30000 -and $_.LocalPort -le 30999 } |
    ForEach-Object { "listen $($_.LocalAddress):$($_.LocalPort) pid=$($_.OwningProcess) $((Get-Process -Id $_.OwningProcess).ProcessName)" }
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne '127.0.0.1' } | ForEach-Object { "ip $($_.IPAddress) $($_.InterfaceAlias)" }
[System.Net.Dns]::GetHostName()
Get-NetFirewallProfile | ForEach-Object { "firewall $($_.Name) enabled=$($_.Enabled) inbound=$($_.DefaultInboundAction)" }
