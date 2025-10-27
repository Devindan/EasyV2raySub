import argparse
import base64
import json
import re

import requests
from bs4 import BeautifulSoup

default_regex = r'(?<=\s)((v[ml]e)?ss|hysteria2)://\S+(?=\s)'
domain_regex = r'([a-zA-Z\d][a-zA-Z\d\-]{1,62}\.){1,3}[a-zA-Z]{2,63}'
request_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36'
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--urls',
                        required=True,
                        nargs='+',
                        help='One or more websites that contain links with the protocol prefixes "hysteria2", '
                             '"vmess://", "vless://", and "ss://".')
    parser.add_argument('-ar', '--additional-regex',
                        required=False,
                        help='Add more regex patterns to match links (optional).')
    parser.add_argument('-o', '--output-file',
                        required=False,
                        default='links.txt',
                        help='Specify a file to write the output to.')
    return parser.parse_args()


def match_links(regex, text):
    results = []
    matches = re.finditer(regex, text)
    for match in matches:
        if match:
            results.append(match.group())
    return results


def get_links(urls, additional_regex):
    all_links = []
    for url in urls:
        try:
            response = requests.get(url, headers=request_headers)
            response.raise_for_status()
            html_content = response.text

            soup = BeautifulSoup(html_content, 'html.parser')
            page_text = soup.get_text()

            all_links.extend(match_links(default_regex, page_text))
            if additional_regex:
                all_links.extend(match_links(additional_regex, page_text))

        except requests.exceptions.RequestException as e:
            print(f"Error fetching the URL: {e}")
    return all_links


# Change the name after the '#' character at the end of the link
def change_node_name(links):
    new_links = []
    for link in links:
        try:
            link_parts = link.split('#')
            if len(link_parts) == 2:
                new_name = re.sub(domain_regex, "EasyV2raySub", link_parts[1])
                new_links.append(link_parts[0] + '#' + new_name)
            else:
                link_parts = link.split("://")
                link = base64.b64decode(link_parts[1].encode('ascii')).decode('utf-8')
                json_dict = json.loads(link)
                json_dict['ps'] = re.sub(domain_regex, "EasyV2raySub", json_dict['ps'])
                encode_link = base64.b64encode(bytes(json.dumps(json_dict), 'utf-8')).decode('utf-8')
                new_links.append(link_parts[0] + '://' + encode_link)
        except:
            new_links.append(link)
    return new_links


def write_links_to_file(links, file_path):
    links = change_node_name(links)
    links_str = "\n".join(links)
    links_base64 = base64.b64encode(links_str.encode('utf-8'))

    with open(file_path, 'w') as file:
        file.write(links_base64.decode('utf-8'))


if __name__ == "__main__":
    args = parse_args()
    links = get_links(args.urls, args.additional_regex)
    write_links_to_file(links, args.output_file)
