**About**

This is a small tool I wrote that lets you connect the gamecube controller via USB to make it usable on Steam.
All it does is connect to the plugged in controller and send the 2 commands to initialize it and set the LED (idk if more are needed). Afterwards it stops the USB connection and connects via HID. Then it outputs the buttons sent via HID to check if it worked.

**How to use**

After you press connect and see your inputs work you can close the window. You should then be able to configure the controller in steam successfully. For me I only had to configure once, on later uses I just had to use the tool and steam remembered the configured controller.

**DISCLAIMER**

I take **NO** responsibility for any damages done by the code. I am an amateur that did this for fun / own use.
**USE AT YOUR OWN RISK!** Idk if i handle threads there correctly, especially when closing the window and the HID process is still running. Idk if it closes.
Also the website sends way more commands. I only send the initial one and the LED command. I dont know if thats the right way to do it.

**Special Thanks**

Big thanks to handheldlegend for letting me use his code in this and Nohzockt for his code.
