""" Garage Gate Opener Frontend """
import subprocess
import flask

app = flask.Flask(__name__)
app.config["DEBUG"] = False


def pulse():
    """Run the radio code as a subprocess"""
    if app.config["DEBUG"]:
        # Run in a mode where no radio transmission is sent
        radio_args = ["/usr/bin/python3", "garage_rfm69.py", "-t"]
    else:
        # Run in live mode, sending the radio transmission
        radio_args = ["/usr/bin/python3", "garage_rfm69.py", "-d"]
    try:
        callout = subprocess.run(
            radio_args,
            capture_output=True,
            check=True,
        )
        print("exit status:", callout.returncode)
        print("stdout:", callout.stdout.decode())
        print("stderr:", callout.stderr.decode())
        return (bool(callout.returncode == 0), callout.stdout.decode())
    except subprocess.CalledProcessError as err:
        print("exit status:", err.returncode)
        print("stdout:", err.stdout.decode())
        print("stderr:", err.stderr.decode())
        return (bool(err.returncode == 0), err.stderr.decode())


@app.route("/", methods=["GET"])
def mainpage():
    """help"""
    return (
        '<div style="   display: flex;justify-content: center;align-items: center;'
        'height: 100%;border: 3px solid green;  " ><p>Garage Gate</p> </div>'
    )


@app.route("/control", methods=["GET"])
def control():
    """control"""
    # Mocking a Sonoff relay?
    # GET /control?cmd=Pulse,doorRelayPin,1,500
    cmd = flask.request.args.get("cmd", default=False, type=str)

    # We only respond to cmd control requests
    if not cmd:
        return (
            '<div style="   display: flex;justify-content: center;align-items: center;'
            'height: 100%;border: 3px solid red;" ><p style="font-size: 300%">Nope</p> </div>',
            503,
        )

    # If we do get a 'Pulse' cmd, then call the radio function
    if cmd.split(",")[0] == "Pulse":
        returncode, returntext = pulse()
        if returncode:
            return (
                f'<div style="display: flex;justify-content: center;align-items: center;'
                f'height: 25%;border: 5px solid green;" ><p style="font-size: 300%">'
                f"Gate responds {returncode}..."
                f"</div><br><pre><code>{returntext}</code></pre></p>"
            )
        return (
            f'<div style="display: flex;justify-content: center;align-items: center;'
            f'height: 25%;border: 5px solid red;" ><p style="font-size: 300%">'
            f"Gate responds {returncode}..."
            f"</div><br><pre><code>{returntext}</code></pre></p>",
            503,
        )

    # If the cmd isn't for a 'Pulse', then provide some vague feedback
    return (
        '<div style="display: flex;justify-content: center;align-items: center;'
        'height: 25%;border: 5px solid red;"><p style="font-size: 300%">'
        "Wrong command</p></div>",
        503,
    )


app.run(host="0", port="80")
