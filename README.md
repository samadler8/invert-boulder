# 🌁 Boulder Inversion Tracker & Predictor

An interactive, real-time web application that predicts temperature inversions and fog decks over Boulder, Colorado. It compares atmospheric conditions across three local elevation landmarks: **City of Boulder (5,400 ft)**, **1st Flatiron Top (7,200 ft)**, and **Green Mountain Summit (8,100 ft)**.

Designed for hikers, trail runners, and photographers looking to catch sunrise above a sea of clouds.

![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat&logo=html5&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=flat&logo=tailwind-css&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat&logo=javascript&logoColor=black)
![Open-Meteo API](https://img.shields.io/badge/Open--Meteo%20API-Free-blue)

---

## 🌟 Key Features

* **3D SVG Terrain Cross-Section:** An interactive elevation profile showing whether the City of Boulder, the 1st Flatiron, and Green Mountain summit are in the fog or standing above the clouds.
* **Open-Meteo API Integration:** Pulls hourly atmospheric sounding data for Boulder (Lat: `40.0150`, Lon: `-105.2705`), including surface temperatures, dew points, relative humidity, wind vectors, and 750hPa pressure-level temps.
* **5-Factor Scoring Algorithm:** Evaluates low cloud cover, upper-sky clarity, thermal cap strength, surface saturation, and upslope vs. downslope wind dynamics.
* **Interactive 24-Hour Timeline Chart:** Toggle between **Inversion Probability (%)** and **Cloud Ceiling Elevation (ft)** hour-by-hour.
* **7-Day Outlook:** Click any day in the extended forecast to inspect its peak morning window.
* **Scenario Presets:** Instantly test how the application handles classic inversions, high cloud decks, socked-in fog, and downslope Chinook windstorms.
* **Multi-Page Explanations:** Includes dedicated `guide.html` (usage & terminology) and `science.html` (meteorological math & algorithms).

---

## 📂 Repository Structure

```text
invert-boulder/
├── index.html          # Main Dashboard & Interactive Predictor
├── guide.html          # User Guide & Terminology Page
├── science.html        # Meteorological Science & Algorithm Docs
├── README.md           # Project Documentation
└── .gitignore          # Files to exclude from Git tracking