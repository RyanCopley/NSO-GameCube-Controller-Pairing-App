![](https://github.com/Accolith/GC-controller-enabler/blob/main/Screenshot%202025-07-14%20204357.png)

**IMPORTANT**

Dualshock support not included yet.

**About**

This is a small tool I wrote that lets you connect the gamecube controller via USB to make it usable on Steam.
All it does is connect to the plugged in controller and send the 2 commands to initialize it and set the LED (idk if more are needed). Afterwards it stops the USB connection and connects via HID. Then it outputs the buttons sent via HID to check if it worked.

You can also press the Emulate button after connecting to make it emulate a 360 controller for non-steam games. Im not sure if i converted the analog inputs correctly as the scales are different between controllers.


**How to build**

- Install .NET SDK in Visual Studio
- Build it :D
- Or run "dotnet build WinFormsApp1/WinFormsApp1.csproj -c Release" in the repository.

You might need to change the values for the analog shoulder button emulation. Each controller seems to have varying values for non-pressed, fully pressed, and at the bump. So you might need to adapt them to your controllers values in order to get full coverage and no jumps in values. After pressing Connect, you can live-read the sent values to the left and the emulated values right. By calibrating with the values you get, it should become more accurate.

The 2 options for percentages decide how the analog triggers are handeled:
- 100% at bump means that trigger value goes from 0 at base to 255 at the bump.
- 100% at press means that the trigger value goes from 0 at base to 255 at full press.

**How to use**

After you press connect and see your inputs work you can close the window. You should then be able to configure the controller in steam successfully. For me I only had to configure once, on later uses I just had to use the tool and steam remembered the configured controller.

Optional, you can also press the Emulate button. The tool then emulates a 360 controller for simpler use in non-steam games etc + the analog shoulder buttons then work. You need to have [ViGEmBus](https://github.com/nefarius/ViGEmBus) installed for it to work.

**DISCLAIMER**

I take **NO** responsibility for any damages done by the code. I am an amateur that did this for fun / own use.
**USE AT YOUR OWN RISK!** Idk if i handle threads there correctly, especially when closing the window and the HID process is still running. Idk if it closes.
Also the website sends way more commands. I only send the initial one and the LED command. I dont know if thats the right way to do it.

**Special Thanks**

Big thanks to handheldlegend for letting me use his code in this and Nohzockt for his code.

**LICENSES**

HidLibrary: MIT License

LibUsbDotNet: GNU Lesser General Public License v3.0

Nefarius.ViGEm.Client: MIT License
