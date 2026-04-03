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
  - MAX98357 I2S DAC amplifier module
  - 3W 4 or 8 ohm speaker
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
  - 5V relay DC- -> Pi pin 14 (ground)
  - 5V relay IN -> Pi pin 11 (GPIO 17)
- 12V to 5V buck converter
  - Buck converter positive -> 12V wall wart positive
  - Buck converter negative -> 12V wall wart negative
  - Buck converter micro USB -> Pi power
- MAX98357 I2S DAC amplifier module
  - Amplifier module G -> Pi pin 6 (ground)
  - Amplifier module V -> Pi pin 4 (5V supply)
  - Amplifier module BCLK -> Pi pin 12 (GPIO 18/PCM CLK)
  - Amplifier module LRCLK -> Pi pin 35 (GPIO 19/PCM FS)
  - Amplifier module DIN -> Pi pin 40 (GPIO 21/PCM DOUT)
- Raspberry Pi pins
  - Pi pin 2 (5V supply) -> 5V relay DC+
  - Pi pin 4 (5V supply) -> amplifier module V
  - Pi pin 6 (ground) -> amplifier module G
  - Pi pin 11 (GPIO 17) -> 5V relay IN
  - Pi pin 12 (GPIO 18/PCM CLK) -> amplifier module BCLK
  - Pi pin 14 (ground) -> 5V relay DC-
  - Pi pin 35 (GPIO 19/PCM FS) -> amplifier module LRCLK
  - Pi pin 40 (GPIO 21/PCM DOUT) -> amplifier module DIN

#### Software

Install the Raspberry Pi Imager at [https://www.raspberrypi.com/software/](https://www.raspberrypi.com/software/)
Flash the 32GB microSD card with Raspberry Pi OS Lite (this is a headless version of the normal OS).
Install the microSD card into the Raspberry Pi and power it on. You can now SSH into the Pi from an external device.

-- THE REST BELOW THIS IS A TEMPLATE --

### Installation

1. Get a free API Key at [https://www.raspberrypi.com/software/](https://www.raspberrypi.com/software/)
2. Clone the repo
   ```sh
   git clone https://github.com/cda9685/goal_horn.git
   ```
3. Install NPM packages
   ```sh
   npm install
   ```
4. Enter your API in `config.js`
   ```js
   const API_KEY = 'ENTER YOUR API';
   ```
5. Change git remote url to avoid accidental pushes to base project
   ```sh
   git remote set-url origin cda9685/goal_horn
   git remote -v # confirm the changes
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

Use this space to show useful examples of how a project can be used. Additional screenshots, code examples and demos work well in this space. You may also link to more resources.

_For more examples, please refer to the [Documentation](https://example.com)_

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ROADMAP -->
## Roadmap

- [ ] Feature 1
- [ ] Feature 2
- [ ] Feature 3
    - [ ] Nested Feature

See the [open issues](https://github.com/cda9685/goal_horn/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Top contributors:

<a href="https://github.com/cda9685/goal_horn/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=cda9685/goal_horn" alt="contrib.rocks image" />
</a>



<!-- CONTACT -->
## Contact

Project Link: [https://github.com/cda9685/goal_horn](https://github.com/cda9685/goal_horn)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* []()
* []()
* []()

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
