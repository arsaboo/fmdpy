"""Downloader for fmdpy."""
import os
import tempfile
import logging
import subprocess

try:
    from typing import Self as _TypingSelf
except ImportError:
    try:
        from typing_extensions import Self as _TypingSelf
        import typing
        typing.Self = _TypingSelf  # Fallback for Python < 3.11
    except ImportError:
        _TypingSelf = None

import lyricsgenius
import music_tag
from pydub import AudioSegment
from fmdpy import config, utils
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
    # Clean URL more aggressively - remove any non-printable characters
    clean_url = ''.join(char for char in url if ord(char) >= 32 and ord(char) < 127)

    # Use curl for all downloads
    base_name = os.path.basename(file_name)
    safe_file_name = os.path.join(os.getcwd(), base_name)
    curl_cmd = [
        'curl', clean_url,
        '-H', 'sec-ch-ua-platform: "Windows"',
        '-H', f'Referer: {clean_url}',
        '-H', 'sec-ch-ua: "Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        '-H', 'sec-ch-ua-mobile: ?0',
        '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        '-H', 'DNT: 1',
        '--output', safe_file_name
    ]

    # Only add Range header for mp4 files
    if file_name.endswith('.mp4'):
        curl_cmd.insert(-2, '-H')
        curl_cmd.insert(-2, 'Range: bytes=0-')

    # Run curl (remove progress bar options for cleaner output)
    if not silent:
        if file_name.endswith('.mp4'):
            print(f"SONG: ({dltext.split('(')[1].split(')')[0] if '(' in dltext else ''}): Downloading...", end='', flush=True)
        else:
            print(f"ART : ({dltext.split('(')[1].split(')')[0] if '(' in dltext else ''}): Downloading...", end='', flush=True)

    result = subprocess.run(curl_cmd + ['-s'], capture_output=True, shell=False)
    if result.returncode != 0:
        if not silent:
            print(" FAILED")
        logging.error(f"curl failed: {result.stderr.decode(errors='replace')}")
        return False

    if not silent:
        print(" DONE")

    # Move the file to the requested file_name if needed
    if safe_file_name != file_name:
        try:
            os.replace(safe_file_name, file_name)
        except Exception as e:
            logging.error(f"Failed to move file: {e}")
            return False

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

                # Try to add artwork, but don't fail if the image is invalid
                try:
                    # Read from the actual temp file, not the NamedTemporaryFile object
                    with open(tf_thumb.name, 'rb') as thumb_file:
                        file_obj['artwork'] = thumb_file.read()
                except Exception as artwork_error:
                    print(f"[WARNING]: Could not add artwork: {artwork_error}")

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
