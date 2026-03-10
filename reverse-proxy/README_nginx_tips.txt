# Tips to ensure video streaming works through Nginx (Range + no buffering)
# Add inside the server/location that proxies to core-api:
# 
#   client_max_body_size 200m;
#   proxy_read_timeout 300s;
#   proxy_send_timeout 300s;
#   proxy_set_header Range $http_range;
#   proxy_set_header If-Range $http_if_range;
#   proxy_request_buffering off;
#   proxy_buffering off;
