def compare_files(file1, file2):
    try:
        with open(file1, 'r') as f1, open(file2, 'r') as f2:
            file1_lines = f1.readlines()
            file2_lines = f2.readlines()

            differences = []
            for i, (line1, line2) in enumerate(zip(file1_lines, file2_lines), start=1):
                if line1 != line2:
                    differences.append((i, line1, line2))

            if differences:
                print(f"Differences found between {file1} and {file2}:")
                for line_num, line1, line2 in differences:
                    print(f"Line {line_num}:")
                    print(f"File 1: {line1.strip()}")
                    print(f"File 2: {line2.strip()}")
            else:
                print(f"No differences found between {file1} and {file2}.")

    except FileNotFoundError as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    file1 = "plc_device_output_real.txt"#input("Enter the path to the first file: ")
    file2 = "plc_device_output.txt"#input("Enter the path to the second file: ")
    compare_files(file1, file2)
