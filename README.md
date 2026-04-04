<!-- Improved compatibility of back to top link: See: https://github.com/othneildrew/Best-README-Template/pull/73 -->
<a id="readme-top"></a>
<!--
*** Thanks for checking out the Best-README-Template. If you have a suggestion
*** that would make this better, please fork the repo and create a pull request
*** or simply open an issue with the tag "enhancement".
*** Don't forget to give the project a star!
*** Thanks again! Now go create something AMAZING! :D
-->



<!-- PROJECT SHIELDS -->
<!--
*** I'm using markdown "reference style" links for readability.
*** Reference links are enclosed in brackets [ ] instead of parentheses ( ).
*** See the bottom of this document for the declaration of the reference variables
*** for contributors-url, forks-url, etc. This is an optional, concise syntax you may use.
*** https://www.markdownguide.org/basic-syntax/#reference-style-links
-->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![LinkedIn][linkedin-shield]][linkedin-url]



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#about-the-project">About The Project</a></li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

[![Product Name Screen Shot][product-screenshot]](https://example.com)

A project built to be run on a Raspberry Pi Zero WH or Raspberry Pi Zero 2W. The scripts included utilize the Pi's 40-pin header, where each pin's functionality is standard across the Pi versions mentioned. Always check your own Pi's pin mapping to ensure the product works correctly.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

This section describes both the hardware and software aspects of the project.

### Prerequisites

#### Hardware

This project requires the following pieces of hardware:
- Core computer and power
  - Raspberry Pi Zero WH or Pi Zero 2W
  - 32GB microSD card (A1/A2 speed class; could get away with less storage)
  - 12V to 5V DC-DC 3A micro USB buck converter
- Light and 12V power
  - 12V red LED rotating beacon light (tabletop style, ~3-4" tall)
  - 12V 3A DC power supply wall wart with female connector
- Switching and control
  - 1-channel 5V relay module (3.3V logic compatible)
- Audio
  - Mini External USB Stereo Speaker (micro USB or with a micro USB to USB-A adapter) 
  - (Optionally, instead of USB speaker) MAX98357 I2S DAC amplifier module
  - (Optionally, instead of USB speaker) 3W 4 or 8 ohm speaker
- Wiring
  - Female-female and male-female DuPont wires
  - 22AWG hook-up wire kit

Wire mapping:
- Lamp
  - Lamp positive -> 5V relay NO
  - Lamp negative -> 12V wall wart negative
- 12V wall wart
  - 12V wall wart positive -> 5V relay COM & buck converter positive
  - 12V wall wart negative -> lamp positive & buck converter negative
- 5V relay
  - 5V relay NO -> lamp positive
  - 5V relay COM -> 12V wall wart positive
  - 5V relay DC+ -> Pi pin 2 (5V supply)
  - 5V relay DC- -> Pi pin 6 (ground)
  - 5V relay IN -> Pi pin 12 (GPIO 18)
- 12V to 5V buck converter
  - Buck converter positive -> 12V wall wart positive
  - Buck converter negative -> 12V wall wart negative
  - Buck converter micro USB -> Pi power
- Raspberry Pi pins
  - Pi pin 2 (5V supply) -> 5V relay DC+
  - Pi pin 6 (ground) -> 5V relay DC-
  - Pi pin 12 (GPIO 18/PCM CLK) -> 5V relay IN

#### Software

Install the Raspberry Pi Imager at [https://www.raspberrypi.com/software/](https://www.raspberrypi.com/software/)
Flash the 32GB microSD card with Raspberry Pi OS Lite (this is a headless version of the normal OS).
Install the microSD card into the Raspberry Pi and power it on. You can now SSH into the Pi from an external device.

### Installation

1. Clone the repo
   ```sh
   git clone https://github.com/cda9685/goal_horn.git
   ```
2. Start a cron job:
  `sudo crontab -e`
  Add the following to the bottom of the file:
```
  @reboot sudo python3 -u /path/to/goal_horn/controller.py >> /path/to/goal_horn/controller.log 2>&1
  @reboot python3 -u /path/to/goal_horn/rangers_monitor.py >> /path/to/goal_horn/rangers_monitor.log 2>&1
  @reboot python3 -u /path/to/goal_horn/yankees_monitor.py >> /path/to/goal_horn/yankees_monitor.log 2>&1
```
  This will start the script in the background on boot and write its status to a log.
  
3. Set up a log rotation:
  `sudo vim /etc/logrotate.d/goal_horn`
  Add the following:
  ```
  /home/coledallen/projects/goal_horn/*.log {
          daily
          rotate 3
          compress
          missingok
          notifempty
          copytruncate
  }
  ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

These scripts are designed to run at boot and remain running in the background. In each script, there are static variables that can be edited to change the functionality of the script:

- rangers_monitor.py
  - RANGERS_TEAM_ID: The acronym for the NHL team that the script will track
  - POLL_INTERVAL: How often the script checks the API during gametime
  - IDLE_INTERVAL: How often the script checks the API with no active game
  - STREAM_DELAY_SECONDS: The delay between the API and streaming service
  - PRIORITY: The priority given to the controller; if two scripts activate the light at the same time, the script with a higher priority (lower integer) will activate first
- yankees_monitor.py
  - YANKEES_TEAM_ID: The ID of the MLB team that the script will track
  - POLL_INTERVAL: How often the script checks the API during gametime
  - IDLE_INTERVAL: How often the script checks the API with no active game
  - STREAM_DELAY_SECONDS: The delay between the API and streaming service
  - PRIORITY: The priority given to the controller; if two scripts activate the light at the same time, the script with a higher priority (lower integer) will activate first
- controller.py
  - GOAL_LIGHT_PIN: The GPIO pin used to trip the relay (NOT the physical pin number)
  - ALSA_DEVICE: The card and device value assigned to the USB speaker
  - POLL_INTERVAL: How often the script will view the event queue from the other scripts (changing is NOT recommended)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ROADMAP -->
## Roadmap

- [ ] Add a branch for users using the MAX98357 I2S DAC amplifier module
- [ ] Add NFL script (Miami Dolphins)
- [ ] Add NBA script (New York Knicks)

See the [open issues](https://github.com/cda9685/goal_horn/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Project Link: [https://github.com/cda9685/goal_horn](https://github.com/cda9685/goal_horn)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[contributors-shield]: https://img.shields.io/github/contributors/cda9685/goal_horn.svg?style=for-the-badge
[contributors-url]: https://github.com/cda9685/goal_horn/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/cda9685/goal_horn.svg?style=for-the-badge
[forks-url]: https://github.com/cda9685/goal_horn/network/members
[stars-shield]: https://img.shields.io/github/stars/cda9685/goal_horn.svg?style=for-the-badge
[stars-url]: https://github.com/cda9685/goal_horn/stargazers
[issues-shield]: https://img.shields.io/github/issues/cda9685/goal_horn.svg?style=for-the-badge
[issues-url]: https://github.com/cda9685/goal_horn/issues
[license-shield]: https://img.shields.io/github/license/cda9685/goal_horn.svg?style=for-the-badge
[license-url]: https://github.com/cda9685/goal_horn/blob/master/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/coledallen
[product-screenshot]: images/screenshot.png
<!-- Shields.io badges. You can a comprehensive list with many more badges at: https://github.com/inttter/md-badges -->
[Next.js]: https://img.shields.io/badge/next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white
[Next-url]: https://nextjs.org/
[React.js]: https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB
[React-url]: https://reactjs.org/
[Vue.js]: https://img.shields.io/badge/Vue.js-35495E?style=for-the-badge&logo=vuedotjs&logoColor=4FC08D
[Vue-url]: https://vuejs.org/
[Angular.io]: https://img.shields.io/badge/Angular-DD0031?style=for-the-badge&logo=angular&logoColor=white
[Angular-url]: https://angular.io/
[Svelte.dev]: https://img.shields.io/badge/Svelte-4A4A55?style=for-the-badge&logo=svelte&logoColor=FF3E00
[Svelte-url]: https://svelte.dev/
[Laravel.com]: https://img.shields.io/badge/Laravel-FF2D20?style=for-the-badge&logo=laravel&logoColor=white
[Laravel-url]: https://laravel.com
[Bootstrap.com]: https://img.shields.io/badge/Bootstrap-563D7C?style=for-the-badge&logo=bootstrap&logoColor=white
[Bootstrap-url]: https://getbootstrap.com
[JQuery.com]: https://img.shields.io/badge/jQuery-0769AD?style=for-the-badge&logo=jquery&logoColor=white
[JQuery-url]: https://jquery.com 
