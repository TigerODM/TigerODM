import os
import time

def process_text_files(enqueue_dir, exchange_dir):
    """
    Process text files from enqueue_dir and create sequentially numbered files in exchange_dir/waiting_room,
    each containing the original file name.

    Args:
        enqueue_dir (str): Path to the directory containing .txt files to process.
        exchange_dir (str): Path to the directory where waiting_room will be created.
    """

    enqueue_dir=enqueue_dir.replace("\\","/")
    exchange_dir = exchange_dir.replace("\\", "/")
    if enqueue_dir[-1]!="/":
        enqueue_dir+="/"

    if exchange_dir[-1]!="/":
        exchange_dir+="/"

    try:
        # Get list of .txt files in enqueue_dir (non-recursive) and sort them chronologically
        todolistfile = sorted(
            (f for f in os.listdir(enqueue_dir) if f.endswith(".txt")),
            key=lambda f: os.path.getmtime(os.path.join(enqueue_dir, f))
        )

        # Define waiting_room directory path
        waiting_room = os.path.join(enqueue_dir, "waiting_room")

        # Create waiting_room directory if it does not exist
        if not os.path.exists(waiting_room):
            os.makedirs(waiting_room)

        # Find the next available sequential filename
        existing_files = sorted(
            (f for f in os.listdir(waiting_room) if f.endswith(".txt") and f[:8].isdigit()),
            key=lambda f: int(f[:8])
        )
        written_files = []
        for existing_file in existing_files:
            with open(os.path.join(waiting_room, existing_file), "r", encoding="utf-8") as f:
                written_files.append(f.read().strip()+".txt")
        next_number = 1 if not existing_files else int(existing_files[-1][:8]) + 1

        # Process each file in todolistfile
        for filename in todolistfile:
            new_filename = f"{next_number:08d}.txt"
            if filename in written_files:
                continue
            new_dir=exchange_dir + filename[:-4]

            if not os.path.exists(new_dir):
                os.makedirs(new_dir)

            exchange_file_path = new_dir + "/ready_to_get_instruction.txt"
            with open(exchange_file_path, "w", encoding="utf-8") as toto:
                pass
            toto.close()
            new_file_path = os.path.join(waiting_room, new_filename)

            # Write the original filename inside the new file
            with open(new_file_path, "w", encoding="utf-8") as new_file:
                new_file.write(filename[:-4])
            new_file.close()

            with open(new_file_path[:-3]+"tkt", "w", encoding="utf-8") as new_file2:
                pass
            new_file2.close()


            next_number += 1

    except Exception as e:
        print(f"Error: {e}")

def loop_process_text_files(enqueue_dir, exchange_dir):
    while True:
        try:
            process_text_files(enqueue_dir, exchange_dir)
        except Exception as e:
            print(e)
        time.sleep(0.5)


if __name__ == "__main__":
    loop_process_text_files("C:/toto_titi/in/","C:/toto_titi/out/")
