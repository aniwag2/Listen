import pvporcupine
from pvrecorder import PvRecorder
import os
import wave
import struct
import datetime
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv
from email.mime.text import MIMEText

# --- Load Environment Variables ---
load_dotenv()

PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY")
WAKE_WORD_MODEL_PATH = os.getenv("WAKE_WORD_MODEL_PATH")
TEMP_AUDIO_DIR = os.getenv("TEMP_AUDIO_DIR", "temp_recordings") # Default if not set
RECORDING_DURATION_SECONDS = int(os.getenv("RECORDING_DURATION_SECONDS", 15)) # Default if not set

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD") # This is an App Password for Gmail!
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587)) # Default if not set

# --- Ensure Output Directory Exists for Temporary Files ---
os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)

# --- Email Function ---
def send_audio_email(file_path, sender_email, sender_password, receiver_email):
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = f"Audio Recording from Voice Trigger - {os.path.basename(file_path)}"

    # Email body (CORRECTED)
    body = "Please find the attached audio recording."
    text_part = MIMEText(body, 'plain') # Create the text part with the body
    # If you really need to add a header to the text part (unusual for the main body), do it like this:
    # text_part.add_header('Content-Disposition', 'inline', filename="message.txt")
    msg.attach(text_part)

    # Attach the audio file
    try:
        with open(file_path, "rb") as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(file_path)}")
        msg.attach(part)
    except FileNotFoundError:
        print(f"Error: Attachment file not found at {file_path}")
        return False
    except Exception as e:
        print(f"Error attaching file: {e}")
        return False

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls() # Enable TLS encryption
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, receiver_email, text)
        server.quit()
        print(f"Email with {os.path.basename(file_path)} sent successfully to {receiver_email}!")
        return True
    except smtplib.SMTPAuthenticationError:
        print("SMTP Authentication Error: Check your sender email and App Password.")
        print("If using Gmail, ensure you've generated an App Password for this application.")
        return False
    except smtplib.SMTPServerDisconnected:
        print("SMTP Server Disconnected: Check your SMTP_SERVER and SMTP_PORT settings, or internet connection.")
        return False
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

# --- Main Program Logic ---
print("Initializing...")

# Initialize Porcupine for wake word detection
try:
    porcupine = pvporcupine.create(
        access_key=PICOVOICE_ACCESS_KEY,
        keyword_paths=[WAKE_WORD_MODEL_PATH]
    )
except pvporcupine.PorcupineError as e:
    print(f"Failed to initialize Porcupine: {e}")
    print("Please ensure your AccessKey and model paths are correct in the .env file.")
    exit()
except Exception as e:
    print(f"An unexpected error occurred during Porcupine initialization: {e}")
    exit()

# Initialize PvRecorder for low-latency audio capture
try:
    recorder = PvRecorder(device_index=-1, frame_length=porcupine.frame_length)
    recorder.start()
except Exception as e:
    print(f"Failed to initialize PvRecorder: {e}")
    print("Ensure your microphone is connected and drivers are installed.")
    exit()

recording = False
audio_frames = []
recording_start_time = None

print("Listening for wake word...")

try:
    while True:
        pcm = recorder.read()
        keyword_index = porcupine.process(pcm)

        if keyword_index == 0: # Assuming the first (and only) model is the wake word
            if not recording:
                print(f"Detected wake word. Starting recording for {RECORDING_DURATION_SECONDS} seconds...")
                recording = True
                audio_frames = []
                recording_start_time = time.time()

        if recording:
            audio_frames.append(pcm)

            current_time = time.time()
            elapsed_time = current_time - recording_start_time

            if elapsed_time >= RECORDING_DURATION_SECONDS:
                print(f"Recording duration ({RECORDING_DURATION_SECONDS}s) reached. Stopping recording and preparing for email...")
                recording = False
                recording_start_time = None

                if audio_frames:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_filename = os.path.join(TEMP_AUDIO_DIR, f"recording_{timestamp}.wav")

                    # Save the recorded audio temporarily
                    try:
                        with wave.open(temp_filename, 'wb') as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(porcupine.sample_rate)
                            wf.writeframes(b''.join(struct.pack('h' * len(frame), *frame) for frame in audio_frames))
                        print(f"Temporary audio saved to: {temp_filename}")

                        # Send the email
                        print("Attempting to send email...")
                        email_sent = send_audio_email(temp_filename, SENDER_EMAIL, SENDER_APP_PASSWORD, RECEIVER_EMAIL)

                        # Delete the temporary file if email was sent successfully
                        if email_sent:
                            os.remove(temp_filename)
                            print(f"Temporary file {temp_filename} deleted.")
                        else:
                            print(f"Email failed to send. Temporary file {temp_filename} not deleted.")

                    except Exception as e:
                        print(f"Error saving temporary audio or sending email: {e}")
                    finally:
                        audio_frames = []
                else:
                    print("No audio recorded to save.")
                print("Listening for wake word...")

        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nStopping...")
finally:
    if recorder is not None:
        recorder.stop()
        recorder.delete()
    if porcupine is not None:
        porcupine.delete()
    print("Clean up complete.")