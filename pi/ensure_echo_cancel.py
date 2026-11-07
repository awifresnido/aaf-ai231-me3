"""Idempotently prepare a JV801P echo-cancel pair before local bot startup."""
import json
import subprocess

SOURCE_MASTER = "alsa_input.usb-JOUNIVO_JOUNIVO_JV801P_20210908-00.mono-fallback"
SINK_MASTER = "alsa_output.usb-JOUNIVO_JOUNIVO_JV801P_20210908-00.analog-stereo"
SOURCE = "voice_agent_aec_source"
SINK = "voice_agent_aec_sink"


def listing(kind):
    result = subprocess.run(["pactl", "--format=json", "list", kind], text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def main():
    sources = {item["name"]: item for item in listing("sources")}
    sinks = {item["name"]: item for item in listing("sinks")}
    if SOURCE_MASTER not in sources or SINK_MASTER not in sinks:
        raise RuntimeError("JV801P source and sink must be available before starting the bot")
    expected = ["source_master=" + SOURCE_MASTER, "sink_master=" + SINK_MASTER,
                "source_name=" + SOURCE, "sink_name=" + SINK, "aec_method=webrtc"]
    if SOURCE in sources or SINK in sinks:
        matches = [item for item in listing("modules") if item["name"] == "module-echo-cancel"
                   and all(value in item.get("argument", "") for value in expected)]
        if len(matches) != 1 or SOURCE not in sources or SINK not in sinks:
            raise RuntimeError("Existing echo-cancel device names do not match the expected JV801P pair")
        # PulseAudio 17's module JSON omits its index; device records retain it.
        module = sources[SOURCE]["owner_module"]
        if sinks[SINK]["owner_module"] != module:
            raise RuntimeError("Echo-cancel source and sink must belong to the same filter module")
        print("JV801P echo-cancel pair ready, module", module)
        return
    # Literal quotes are required inside this argument: pactl joins module
    # arguments before PulseAudio parses them. Disable automatic gain changes.
    module = subprocess.check_output(
        ["pactl", "load-module", "module-echo-cancel", *expected,
         "rate=48000", "channels=1",
         'aec_args="analog_gain_control=0 digital_gain_control=0"'], text=True).strip()
    if SOURCE not in {item["name"] for item in listing("sources")} or SINK not in {item["name"] for item in listing("sinks")}:
        raise RuntimeError("PulseAudio did not create both echo-cancel devices")
    print("Created JV801P echo-cancel pair, module", module)


if __name__ == "__main__":
    main()
