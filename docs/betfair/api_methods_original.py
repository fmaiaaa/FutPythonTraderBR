from dotenv import load_dotenv
import os
import requests
import urllib

load_dotenv()

EMAIL=os.getenv('EMAIL')
SENHA=os.getenv('SENHA')
APP_KEY=os.getenv('APP_KEY')


def session_token() -> str:
  """
  Pega o token de sessão "login" na betfair.
  
  :return: Token
  :rtype: str
  """
  payload = f'username={EMAIL}&password={SENHA}'
  headers = {'X-Application': APP_KEY, 'Content-Type': 'application/x-www-form-urlencoded'}
  
  resp = requests.post('https://identitysso-cert.betfair.bet.br/api/certlogin', data=payload, cert=('client-2048.crt', 'client-2048.key'), headers=headers)
  
  if resp.status_code == 200:
    resp_json = resp.json()
    print(resp_json['loginStatus'])
    return resp_json['sessionToken']
  else:
    print("Request failed.")


def callAping(jsonrpc_req: str) -> dict:
    """
      Bate na API da betfair para coletar dados
      
      args: 
      
        jsonrpc_req (_str_) -> payload padronizado para betfair

      :return: Dict com informações
      :rtype: dict
    """
    url = "https://api.betfair.bet.br/exchange/betting/json-rpc/v1"
    headers = {'X-Application': APP_KEY, 'X-Authentication': session_token(), 'content-type': 'application/json'}
    try:
        req = urllib.request.Request(url, jsonrpc_req.encode('utf-8'), headers)
        response = urllib.request.urlopen(req)
        jsonResponse = response.read()
        return jsonResponse.decode('utf-8')
    except urllib.error.URLError as e:
        print (e.reason) 
        print ('Oops no service available at ' + str(url))
        exit()
    except urllib.error.HTTPError:
        print ('Oops not a valid operation from the service ' + str(url))
        exit()