
Install as systemd service : `sudo systemctl start Garage`
```
sudo apt install -y authbind
sudo touch /etc/authbind/byport/80
sudo chmod 777 /etc/authbind/byport/80
authbind python3 garage.py
```


## TODO
- Test systemd install process
- Resolve RFM69 radio raw packet issues
  - Change RFM69 FIFO triggers?
