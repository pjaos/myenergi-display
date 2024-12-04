# Running the myenergi-display server.
The Raspberry Pi zero 2 W (RPi) runs Raspberry Pi's version of Linux (Raspberry Pi OS bookworm) but the python code should run on any platform (Ubuntu, Windows etc) that supports python3.12.

Before starting the installation you must have the RPi imager software installed on your desktop PC as detailed [here](https://www.raspberrypi.com/software/)

## RPi Hardware
I used a [Raspberry Pi zero 2 W](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/) although the software should work on any any aarch64 raspberry pi running the latest (version 12/bookworm) Raspberry Pi OS image.

## Software installation

- Create an SD Card using the RPI Imager software. Use the RPi image options to

    - Setup your wifi network and password.
    - Enable ssh.

- Install the SD card into the RPi and power it up. As you entered your WiFi details in the previous step it should connect to your WiFi network. You will need to find out it's IP address on your WiFi network so that you can connect to it via ssh. Your routers DHCP server should have assigned an IP address to the RPi device. The user interface on your router should show the IP address that the router assigned to the RPi device when it booted.

- Connect to the RPi via ssh.
    - If the IP address if the RPi device was 192.168.0.20 and the user you created when using the RPI Imager software was auser then you should be able to connect to the Raspberry Pi using a command such as 'ssh auser@192.168.0.20'.
- Check the operating system of the RPi Zero 2 W as shown below.

```
auser@rpi-2-w:~ $ lsb_release -a
No LSB modules are available.
Distributor ID:	Debian
Description:	Debian GNU/Linux 12 (bookworm)
Release:	12
Codename:	bookworm
```

- Install pipx

pipx allows python applications to be executed in isolated environments. Run the commands below to install the pipx software.

```
sudo apt update
sudo apt install pipx
pipx ensurepath
sudo pipx ensurepath
```

- Drop ssh connection to RPi and reconnect. This ensures that the pipx executable is in the path when you reconnect.
- Copy the installers/myenergi_display-0.173-py3-none-any.whl (version may change) file to /tmp on the RPi. There are several ways to do this.
    - Use scp to copy the file as detailed [here](https://www.cyberciti.biz/faq/how-to-copy-and-transfer-files-remotely-on-linux-using-scp-and-rsync/).
    - Remove the SD card from the RPi. Plug it into your PC and copy it directly.
- Install the myenergi-display software as shown below

```
auser@rpi-2-w:~ $ sudo pipx install /tmp/myenergi_display-0.161-py3-none-any.whl
  installed package myenergi-display 0.165, installed using Python 3.10.12
  These apps are now globally available
    - myenergi_display
done! ✨ 🌟 ✨
```

The above command (myenergi_display) should take about 5 minutes to install onto the RPi. The
software is installed as root user so that it can be auto started when the RPi starts/boots up.

The software is now installed onto the raspberry Pi.



