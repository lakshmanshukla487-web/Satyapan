Put CIDR lists here, one network per line (# starts a comment). The file name sets the category:
  tor*.txt        -> the Tor network
  vpn*.txt        -> VPN services
  proxy*.txt      -> anonymising / open proxies
  anything else   -> data centre / hosting ranges
Fill the folder with:  python scripts/update_ip_lists.py
The files are re-read automatically within a minute of changing. Without any list only the WebRTC leak, proxy-header and
IP-change checks (and an optional reputation API) work; the report says which sources were used.
