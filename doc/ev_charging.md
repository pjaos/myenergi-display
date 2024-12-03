# Charging your EV
The app can be used to charge your EV. The app will select the times when your electricity is cheapest.

You must select the ZAPPI tab to display the screen shown below.

<img src="images/zappi_tab.png" width="300"/>

The three fields at the top of the page are

- Target EV Charge (%)

    You may enter how full you want the EV battery to be when the charge is complete. This can be set up to 100%.

- Current EV charge (%)

    You must enter the current state of charge of your EV battery in order that sufficient energy to reach teh above target EV charge can be delivered.

- Ready by

    This is the time in HH:MM that you wish the car to be charged to the required level.

The buttons have the following functions.

- CALC

    Calculate the optimal charge schedule to give the lowest cost charge.

- SET

    Set the displayed charge schedule. This sends the charge schedule to the myenergi system so that your zappi charges your EV.

- GET

    Get the schedule that the myenergi system holds for your zappi charger. It may take some time for this to update after setting the charge schedule.

- CLEAR

    Clear the charge schedule for your zappi charger. After selecting this it may take some time for the schedule to be cleared/reset.


The example below shows how to setup an EV charge.

- Enter the required target EV charge level
- Enter the current EV charge level
- Select the CALC button

The following is then displayed

<img src="images/zappi_calc_charge_1.png" width="500"/>

This shows the calculated time required to achieve the charge level. In this case the target charge level was 80% and the calculated charge would charge the battery to 79%. The difference is because the zappi charges in 15 minute chunks. Therefore the exact target charge level may not be achieved. In such a situation you can adjust the target charge level entered slightly. This allows you to add an extra 15 minutes of charge. In the above example if the target charge level is changed to 82% the charge time changes to 195 minutes, as shown below.

<img src="images/zappi_calc_charge_2.png" width="500"/>

The graph shows the tariff in green and the charge period in red. You may zoom into the graph by dragging over the required area. The X in the toolar at the top of the graph can be used to autoscale the graph back to its original size.

Once you are happy with the selected charge times you can press the SET button. If the schedule is successfully uploaded to the myenergi system the SET button background will turn purple to indicate that a schedule has been set. The SET button will turn green while the EV is being charged.

If you wish to check the schedule that has been uploaded to the myenergi system you may select the GET button. It takes some time (5 minutes or more sometimes) for the myenergi system to update the charge schedule. If the GET button is selected before the myenergu zappi charge schedule has been updated the following will be displayed.

<img src="images/zappi_calc_charge_4.png" width="500"/>

If you wait some time before the GET button is selected the schedule will be displayed as shown below.

<img src="images/zappi_calc_charge_5.png" width="500"/>

In the above example the Intelligent Octopus Go tariff was used. However if (in the settings tab) the Octopus Agile tariff is selected then when the CALC button is selected the variable tariff (in 30 minute chunks) for the next period of time is read from the internet. If using the Agile tariff it is recommended that you select the CALC button after 4:00 - 4:15 PM as this is when the Agile tariff values are updated for the next day.

An example of selecting the CALC button when the Octopus Agile tariff was configured is shown below.

<img src="images/zappi_calc_charge_6.png" width="500"/>


### Note

- In some cases (E.G if the weather is very cold) you may find that your EV does not charge at full rate (7.4 or 22 kW) until the battery has warmed up. In such situations you may find the target charge level is not reached using the schedule set.


