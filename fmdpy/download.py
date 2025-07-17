"""Downloader for fmdpy."""
import os
import tempfile
import logging
import subprocess

import lyricsgenius
import music_tag
import requests
from pydub import AudioSegment
from tqdm import tqdm
from fmdpy import config, headers, utils
from fmdpy.api import get_song_urls

# Setup logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def convert_audio(input_file_path, output_file_path, bitrate, dlformat):
    try:
        input_audio = AudioSegment.from_file(input_file_path, "mp4")
    except FileNotFoundError:
        print(f"Input file {input_file_path} not found.")
        return False
    except Exception as e:
        print(f"Error reading input file {input_file_path}: {e}")
        return False
    try:
        input_audio.export(output_file_path, format=dlformat, bitrate=bitrate)
        return True
    except FileNotFoundError:
        print(f"Output file path {output_file_path} not found.")
        return False
    except Exception as e:
        print(f"Error writing output file {output_file_path}: {e}")
        return False

def dlf(url, file_name, silent=0, dltext="", stop_sig=None):
    logging.info(f"Download URL: {url}")
    logging.info(f"URL repr: {repr(url)}")
    # Clean URL more aggressively - remove any non-printable characters
    clean_url = ''.join(char for char in url if ord(char) >= 32 and ord(char) < 127)
    logging.info(f"Cleaned URL: {clean_url}")
    # Use a safe file name for curl if .mp4
    if file_name.endswith('.mp4'):
        base_name = os.path.basename(file_name)
        safe_file_name = os.path.join(os.getcwd(), base_name)
        logging.info(f"Original file_name: {file_name}")
        logging.info(f"Safe file_name: {safe_file_name}")
        curl_cmd = [
            'curl', clean_url,
            '-H', 'sec-ch-ua-platform: "Windows"',
            '-H', f'Referer: {clean_url}',
            '-H', 'sec-ch-ua: "Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
            '-H', 'sec-ch-ua-mobile: ?0',
            '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            '-H', 'DNT: 1',
            '-H', 'Range: bytes=0-',
            '--output', safe_file_name
        ]
        logging.info(f"Running curl: {curl_cmd}")
        result = subprocess.run(curl_cmd, capture_output=True, shell=False)
        if result.returncode != 0:
            logging.error(f"curl failed: {result.stderr.decode(errors='replace')}\nCMD: {curl_cmd}")
            return False
        file_size = os.path.getsize(safe_file_name)
        logging.info(f"Downloaded file size (curl): {file_size} bytes -> {safe_file_name}")
        if file_size < 1024:
            with open(safe_file_name, 'rb') as f:
                snippet = f.read(200)
                try:
                    logging.warning(f"File content preview: {snippet.decode(errors='replace')}")
                except Exception:
                    logging.warning(f"File content preview (raw bytes): {snippet}")
        # Move the file to the requested file_name if needed
        logging.info(f"Checking if move needed: {safe_file_name} != {file_name}")
        if safe_file_name != file_name:
            logging.info(f"Moving file from {safe_file_name} to {file_name}")
            logging.info(f"File exists before move: {os.path.exists(safe_file_name)}")
            try:
                os.replace(safe_file_name, file_name)
                logging.info("File moved successfully")
                logging.info(f"File exists after move: {os.path.exists(file_name)}")
            except Exception as e:
                logging.error(f"Failed to move file: {e}")
                return False
        else:
            logging.info("No move needed, files are the same")
        return True

    # Use only the headers from the working curl command
    custom_headers = {
        'sec-ch-ua-platform': '"Windows"',
        'Referer': url,
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        'DNT': '1',
        'Range': 'bytes=0-'
    }
    session = requests.Session()
    with open(file_name, "wb") as file_obj:
        response = session.get(url, headers=custom_headers, stream=True)
        logging.info(f"HTTP status: {response.status_code}")
        logging.info(f"Response headers: {response.headers}")
        total_length = response.headers.get('content-length')

        if (total_length is None) or (silent):  # no content length header
            file_obj.write(response.content)
        else:
            total_length = int(total_length)
            with tqdm(desc=dltext, total=total_length, \
                    leave=True, unit_scale=True, unit='B') as pbar:
                for data in response.iter_content(chunk_size=4096):
                    pbar.update(file_obj.write(data))
                    if stop_sig and stop_sig.is_set():
                        logging.warning("Download stopped by signal.")
                        return False
    file_size = os.path.getsize(file_name)
    logging.info(f"Downloaded file size: {file_size} bytes -> {file_name}")
    if file_size < 1024:  # If file is suspiciously small, log first 200 bytes as text
        with open(file_name, 'rb') as f:
            snippet = f.read(200)
            try:
                logging.warning(f"File content preview: {snippet.decode(errors='replace')}" )
            except Exception:
                logging.warning(f"File content preview (raw bytes): {snippet}")
    return True

def get_lyric(song_obj):
    """Get lyric."""
    genius = lyricsgenius.Genius(config['API_KEYS']['lyricsgenius'])
    genius.verbose = False
    song = genius.search_song(song_obj.title, song_obj.artist)
    if song:
        return song.lyrics
    return None


def main_dl(
        song_obj,
        dlformat='opus',
        bitrate=250,
        addlyrics=0,
        directory="./",
        filename="$artist-$name-$year",
        dltext=None,
        silent=0,
        stop_sig=None):
    """Main download function for fmdpy."""
    to_delete = []
    get_song_urls(song_obj)
    if song_obj.url == "":
        return None

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=not (os.name == 'nt')) as tf_song:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=not (os.name == 'nt')) as tf_thumb:
            if os.name == 'nt':
                to_delete.append(tf_song.name)
                to_delete.append(tf_thumb.name)

            directory = utils.resolve_string(song_obj, directory)
            os.makedirs(directory, exist_ok=True)
            filename = utils.slugify(utils.resolve_string(song_obj, filename))
            output_file = directory + '/' + filename

            if os.path.isfile(output_file):
                print(f"[WARNING]: File {output_file + '.mp4'} exist, skipping")
                return False

            stat = dlf(song_obj.url, tf_song.name, \
                    dltext=f"SONG: ({dltext})", silent=silent, stop_sig=stop_sig)
            if not stat:
                return stat
            stat = dlf(song_obj.thumb_url, tf_thumb.name, \
                    dltext=f"ART : ({dltext})", silent=silent, stop_sig=stop_sig)
            if not stat:
                return stat

            conversion_success = True
            if dlformat != 'native':
                output_file += f".{dlformat}"
                # convert to desired format.
                conversion_success = convert_audio(tf_song.name, output_file, f'{bitrate}k', dlformat)
                if not conversion_success:
                    print(f"[ERROR]: Failed to convert {tf_song.name} to {output_file}")
                    return False
            else:
                output_file += '.mp4'
                if not os.path.isfile(output_file):
                    # Read from the actual temp file, not the NamedTemporaryFile object
                    with open(tf_song.name, 'rb') as temp_file:
                        with open(output_file, 'wb') as file_obj:
                            file_obj.write(temp_file.read())
                else:
                    print(
                        f"[WARNING]: File {output_file + '.mp4'} exist, skipping")
                    return False

            # Verify the file exists before trying to tag it
            if not os.path.isfile(output_file):
                print(f"[ERROR]: Output file {output_file} does not exist")
                return False

            # Try to tag the file, catch NotImplementedError for unsupported formats
            try:
                file_obj = music_tag.load_file(output_file)
                file_obj['year'] = song_obj.year
                file_obj['title'] = song_obj.title
                file_obj['artist'] = song_obj.artist
                file_obj['album'] = song_obj.album
                file_obj['comment'] = song_obj.copyright \
                    + ', downloaded using (https://github.com/Liupold/fmdpy)'
                file_obj['album'] = song_obj.album
                file_obj['artwork'] = tf_thumb.read()
                if addlyrics:
                    song_lyric = get_lyric(song_obj)
                    if song_lyric:
                        file_obj['lyrics'] = song_lyric
                file_obj.save()
            except NotImplementedError:
                print(f"[WARNING]: Tagging is not supported for this file format: {output_file}")
            except Exception as e:
                print(f"[ERROR]: Failed to add tags to {output_file}: {e}")
                return False

    if len(to_delete) > 0:
        _ = [os.unlink(fname) for fname in to_delete]
    return True
