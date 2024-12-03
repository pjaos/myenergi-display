# Running the myenergi-display server.

You must have the RPi imager software installed on your PC as detailed [here](https://www.raspberrypi.com/software/)

## RPi Hardware
I used a [Raspberry Pi zero 2 W](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/) although the software should work on any any aarch64 raspberry pi running the latest (12/bookworm) raspbian image.

## Software installation

- Create an SD Card using the RPI Imager software. Use the RPi image options to

    - Setup your wifi network and password.
    - Enable ssh and add your public ssh key to it to allow you to log into the RPi without a password.
      You must have previously setup a local ssh key pair (public/private) on the machine you are using to connect from. More
      details on how to create ssh key pairs (public/private) can be found at https://www.ssh.com/academy/ssh/keygen.

- Install the SD card into the RPi. You will need to know the IP address of the RPi zero 2 W on your local network. Your routers DHCP table should show you it's IP address assigned from your local DHCP server on your WiFi network.

- Connect to the RPi via ssh.
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
This allows python applications to be executed in isolated environments.

```
sudo apt update
sudo apt install pipx
pipx ensurepath
sudo pipx ensurepath
```

- Drop ssh connection to RPi and reconnect. This ensures that the pipx executable is in the path when you reconnect.
- Copy the myenergi_display-0.165-py3-none-any.whl (version may change) file to /tmp on the RPi.
- Install the myenergi-display software as shown below

```
auser@rpi-2-w:~ $ sudo pipx install /tmp/myenergi_display-0.161-py3-none-any.whl
  installed package myenergi-display 0.165, installed using Python 3.10.12
  These apps are now globally available
    - myenergi_display
done! ✨ 🌟 ✨

```

The above command should take about 5 minutes to install the 'myenergi_display' application onto the RPi. The
software is installed as root user so that it can be auto started when the Raspberry Pi zero 2 W starts/boots up.

The software is now installed onto the raspberry Pi.

Details of how the myenergi display is used can be found [here](../doc/usage_details.md)