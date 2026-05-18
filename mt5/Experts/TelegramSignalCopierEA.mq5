#property strict

#include <Trade/Trade.mqh>

input string BridgeFolderName = "TelegramSignalCopierBridge";
input int TimerIntervalSeconds = 1;
input int TelegramHeartbeatTimeoutSeconds = 15;
input int MaxSlippagePoints = 30;
input int MaxCommandAgeSeconds = 180;
input string AllowedSymbols = "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,XAGUSD,US30,NAS100,USOIL,SPX500";
input bool AllowMarketOrders = true;
input bool AllowPendingOrders = true;

struct TradeCommand
{
   string request_id;
   long submitted_epoch;
   bool has_submitted_epoch;
   string source_group;
   string message_id;
   string symbol;
   string action;
   string order_type;
   double volume;
   double entry_price;
   bool has_entry_price;
   double stop_loss;
   bool has_stop_loss;
   double take_profit;
   bool has_take_profit;
   string comment;
};

struct TelegramStatus
{
   string listener_state;
   bool telegram_connected;
   long heartbeat_epoch;
   string heartbeat_display;
   string identity;
   string session_name;
   string source_count;
   string last_source_group;
   string last_message_id;
   string last_decision;
   string last_execution_status;
   string last_symbol;
   string last_side;
   string last_order_type;
   string last_entry_price;
   string last_stop_loss;
   string last_take_profits;
   string last_confidence;
   string last_error;
   string last_trade_comment;
};

CTrade trade;
TelegramStatus g_last_status;
bool g_has_last_status = false;
string g_last_chart_comment = "";
string g_last_bridge_request_id = "";
string g_last_bridge_status = "";
string g_last_bridge_message = "";

int OnInit()
{
   trade.SetDeviationInPoints(MaxSlippagePoints);
   EnsureBridgeFolders();
   WriteEAStatus();
   UpdateChartStatus();
   bool auto_trade = (bool)MQLInfoInteger(MQL_TRADE_ALLOWED);
   PrintFormat("TelegramSignalCopierEA initialized. Bridge=%s Symbol=%s AllowedSymbols=%s AutoTrading=%s",
      BridgeFolderName, _Symbol, AllowedSymbols, auto_trade ? "ON" : "OFF");
   if(!auto_trade)
      Print("TelegramSignalCopierEA WARNING: AutoTrading is DISABLED in MT5. Enable it via the toolbar button.");
   EventSetTimer(TimerIntervalSeconds);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   WriteEAStatus();
   Comment("");
}

void OnTimer()
{
   ProcessBridgeCommands();
   UpdateChartStatus();
   WriteEAStatus();
}

void EnsureBridgeFolders()
{
   FolderCreate(BridgeFolderName, FILE_COMMON);
   FolderCreate(BridgeFolderName + "/inbox", FILE_COMMON);
   FolderCreate(BridgeFolderName + "/outbox", FILE_COMMON);
}

void UpdateChartStatus()
{
   TelegramStatus status;
   bool has_status = ReadTelegramStatus(status);
   TelegramStatus display_status = status;

   if(has_status)
   {
      if(g_has_last_status)
         MergeTelegramStatus(display_status, g_last_status);
      g_last_status = display_status;
      g_has_last_status = true;
   }
   else if(g_has_last_status)
   {
      display_status = g_last_status;
      has_status = true;
   }

   string comment = BuildStatusComment(display_status, has_status);
   if(comment != g_last_chart_comment)
   {
      Comment(comment);
      g_last_chart_comment = comment;
   }
}

void MergeTelegramStatus(TelegramStatus &status, const TelegramStatus &fallback)
{
   if(status.listener_state == "")
      status.listener_state = fallback.listener_state;
   if(!status.telegram_connected)
      status.telegram_connected = fallback.telegram_connected;
   if(status.heartbeat_epoch <= 0)
      status.heartbeat_epoch = fallback.heartbeat_epoch;
   if(status.heartbeat_display == "")
      status.heartbeat_display = fallback.heartbeat_display;
   if(status.identity == "")
      status.identity = fallback.identity;
   if(status.session_name == "")
      status.session_name = fallback.session_name;
   if(status.source_count == "")
      status.source_count = fallback.source_count;
   if(status.last_source_group == "")
      status.last_source_group = fallback.last_source_group;
   if(status.last_message_id == "")
      status.last_message_id = fallback.last_message_id;
   if(status.last_decision == "")
      status.last_decision = fallback.last_decision;
   if(status.last_execution_status == "")
      status.last_execution_status = fallback.last_execution_status;
   if(status.last_symbol == "")
      status.last_symbol = fallback.last_symbol;
   if(status.last_side == "")
      status.last_side = fallback.last_side;
   if(status.last_order_type == "")
      status.last_order_type = fallback.last_order_type;
   if(status.last_entry_price == "")
      status.last_entry_price = fallback.last_entry_price;
   if(status.last_stop_loss == "")
      status.last_stop_loss = fallback.last_stop_loss;
   if(status.last_take_profits == "")
      status.last_take_profits = fallback.last_take_profits;
   if(status.last_confidence == "")
      status.last_confidence = fallback.last_confidence;
   if(status.last_error == "")
      status.last_error = fallback.last_error;
   if(status.last_trade_comment == "")
      status.last_trade_comment = fallback.last_trade_comment;
}

string DisplayValue(const string value)
{
   return(value == "" ? "-" : value);
}

string TrimmedCopy(const string value)
{
   string output = value;
   StringTrimLeft(output);
   StringTrimRight(output);
   return(output);
}

bool ReadTelegramStatus(TelegramStatus &status)
{
   int file_handle = FileOpen(BridgeFolderName + "/telegram_status.txt", FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(file_handle == INVALID_HANDLE)
      return(false);

   ZeroMemory(status);
   while(!FileIsEnding(file_handle))
   {
      string line = FileReadString(file_handle);
      int separator = StringFind(line, "=");
      if(separator < 0)
         continue;

      string key = StringSubstr(line, 0, separator);
      string value = StringSubstr(line, separator + 1);
      ApplyTelegramStatusField(status, key, value);
   }

   FileClose(file_handle);
   return(true);
}

void ApplyTelegramStatusField(TelegramStatus &status, const string key, const string value)
{
   if(key == "listener_state")
      status.listener_state = value;
   else if(key == "telegram_connected")
      status.telegram_connected = (value == "1" || value == "true" || value == "TRUE");
   else if(key == "heartbeat_epoch")
      status.heartbeat_epoch = StringToInteger(value);
   else if(key == "heartbeat_display")
      status.heartbeat_display = value;
   else if(key == "identity")
      status.identity = value;
   else if(key == "session_name")
      status.session_name = value;
   else if(key == "source_count")
      status.source_count = value;
   else if(key == "last_source_group")
      status.last_source_group = value;
   else if(key == "last_message_id")
      status.last_message_id = value;
   else if(key == "last_decision")
      status.last_decision = value;
   else if(key == "last_execution_status")
      status.last_execution_status = value;
   else if(key == "last_symbol")
      status.last_symbol = value;
   else if(key == "last_side")
      status.last_side = value;
   else if(key == "last_order_type")
      status.last_order_type = value;
   else if(key == "last_entry_price")
      status.last_entry_price = value;
   else if(key == "last_stop_loss")
      status.last_stop_loss = value;
   else if(key == "last_take_profits")
      status.last_take_profits = value;
   else if(key == "last_confidence")
      status.last_confidence = value;
   else if(key == "last_trade_comment")
      status.last_trade_comment = value;
   else if(key == "last_error")
      status.last_error = value;
}

bool IsHeartbeatFresh(const long heartbeat_epoch)
{
   if(heartbeat_epoch <= 0)
      return(false);

   // Use TimeGMT() — heartbeat_epoch is a UTC Unix timestamp written by Python.
   long age = (long)TimeGMT() - heartbeat_epoch;
   if(age < 0)
      age = 0;
   return(age <= TelegramHeartbeatTimeoutSeconds);
}

string BuildStatusComment(const TelegramStatus &status, const bool has_status)
{
   string output = "Telegram Signal Copier EA\n";
   output += "Bridge: " + BridgeFolderName + "\n";

   if(!has_status)
   {
      output += "Telegram: waiting for listener status\n";
      output += "Start Python listener to confirm chart link";
      return(output);
   }

   string connection_label = "DISCONNECTED";
   if(status.telegram_connected)
      connection_label = IsHeartbeatFresh(status.heartbeat_epoch) ? "CONNECTED" : "STALE";

   output += "Telegram: " + connection_label;
   if(status.listener_state != "")
      output += " (" + status.listener_state + ")";
   output += "\n";

   output += "Account: " + DisplayValue(status.identity) + "\n";
   output += "Heartbeat: " + DisplayValue(status.heartbeat_display) + "\n";
   output += "Sources: " + DisplayValue(status.source_count) + "\n";
   output += "Last source: " + DisplayValue(status.last_source_group) + "\n";
   output += "Message ID: " + DisplayValue(status.last_message_id) + "\n";

   string last_signal = status.last_symbol;
   if(status.last_side != "")
   {
      if(last_signal != "")
         last_signal += " ";
      last_signal += status.last_side;
   }
   if(status.last_order_type != "")
   {
      if(last_signal != "")
         last_signal += " ";
      last_signal += status.last_order_type;
   }
   output += "Last signal: " + DisplayValue(last_signal) + "\n";
   output += "Entry/SL: " + DisplayValue(status.last_entry_price) + " / " + DisplayValue(status.last_stop_loss) + "\n";
   output += "TPs: " + DisplayValue(status.last_take_profits) + "\n";
   output += "Confidence: " + DisplayValue(status.last_confidence) + "\n";
   output += "Decision: " + DisplayValue(status.last_decision) + "\n";
   output += "EA handoff: " + DisplayValue(status.last_execution_status) + "\n";
   output += "Trade tag: " + DisplayValue(status.last_trade_comment) + "\n";
   output += "Error: " + DisplayValue(status.last_error) + "\n";

   return(output);
}

void ProcessBridgeCommands()
{
   string request_ids[];
   int queued_count = ReadQueuedRequestIds(request_ids);
   if(queued_count <= 0)
   {
      // Log only once per minute to avoid spam — use a global timer
      static datetime s_last_no_cmd_log = 0;
      if(TimeCurrent() - s_last_no_cmd_log >= 60)
      {
         PrintFormat("TelegramSignalCopierEA: command queue empty (path=%s/command_queue.txt AutoTrading=%s)",
            BridgeFolderName, (bool)MQLInfoInteger(MQL_TRADE_ALLOWED) ? "ON" : "OFF");
         s_last_no_cmd_log = TimeCurrent();
      }
      return;
   }

   string pending_request_ids[];
   ArrayResize(pending_request_ids, 0);

   for(int i = 0; i < queued_count; i++)
   {
      string request_id = request_ids[i];
      string relative_path = CommandFilePrefix() + request_id + ".txt";
      PrintFormat("TelegramSignalCopierEA found bridge command: %s", request_id);
      TradeCommand command;
      string parse_error = "";
      bool read_ok = ReadTradeCommand(relative_path, command, parse_error);

      if(read_ok)
         ExecuteTradeCommand(command);
      else
      {
         if(parse_error == "Failed to open bridge command file")
         {
            int pending_index = ArraySize(pending_request_ids);
            ArrayResize(pending_request_ids, pending_index + 1);
            pending_request_ids[pending_index] = request_id;
            continue;
         }

         PrintFormat("TelegramSignalCopierEA failed to parse %s: %s", request_id, parse_error);
         WriteResult(request_id, "ERROR", parse_error, 0, 0.0);
      }

      // Delete the processed top-level alias. Python cleans mirrored compatibility
      // files after it observes the result file.
      FileDelete(relative_path, FILE_COMMON);
   }

   RewriteCommandQueue(pending_request_ids);
}

bool ReadTradeCommand(const string relative_path, TradeCommand &command, string &error_message)
{
   int file_handle = FileOpen(relative_path, FILE_READ | FILE_ANSI | FILE_COMMON);
   if(file_handle == INVALID_HANDLE)
   {
      error_message = "Failed to open bridge command file";
      return(false);
   }

   ZeroMemory(command);

   string payload = FileReadString(file_handle, (int)FileSize(file_handle));
   FileClose(file_handle);

   string lines[];
   int line_count = StringSplit(payload, '\n', lines);
   for(int i = 0; i < line_count; i++)
   {
      string line = lines[i];
      StringReplace(line, "\r", "");
      if(line == "")
         continue;

      int separator = StringFind(line, "=");
      if(separator < 0)
         continue;

      string key = StringSubstr(line, 0, separator);
      string value = StringSubstr(line, separator + 1);
      ApplyField(command, key, value);
   }

   if(command.request_id == "")
   {
      error_message = "Command missing request_id";
      return(false);
   }
   if(command.symbol == "")
   {
      error_message = "Command missing symbol";
      return(false);
   }
   if(command.action == "")
   {
      error_message = "Command missing action";
      return(false);
   }
   if(command.volume <= 0.0)
   {
      error_message = "Command volume must be greater than zero";
      return(false);
   }

   return(true);
}

void ApplyField(TradeCommand &command, const string key, const string value)
{
   if(key == "request_id")
      command.request_id = value;
   else if(key == "submitted_epoch" && value != "")
   {
      command.submitted_epoch = StringToInteger(value);
      command.has_submitted_epoch = true;
   }
   else if(key == "source_group")
      command.source_group = value;
   else if(key == "message_id")
      command.message_id = value;
   else if(key == "symbol")
      command.symbol = value;
   else if(key == "action")
      command.action = value;
   else if(key == "order_type")
      command.order_type = value;
   else if(key == "volume")
      command.volume = ParseBridgeDouble(value);
   else if(key == "entry_price" && value != "")
   {
      command.entry_price = ParseBridgeDouble(value);
      command.has_entry_price = true;
   }
   else if(key == "stop_loss" && value != "")
   {
      command.stop_loss = ParseBridgeDouble(value);
      command.has_stop_loss = true;
   }
   else if(key == "take_profit" && value != "")
   {
      command.take_profit = ParseBridgeDouble(value);
      command.has_take_profit = true;
   }
   else if(key == "comment")
      command.comment = value;
}

double ParseBridgeDouble(const string raw_value)
{
   string normalized = raw_value;
   StringTrimLeft(normalized);
   StringTrimRight(normalized);
   if(normalized == "")
      return(0.0);

   bool negative = false;
   bool seen_separator = false;
   bool saw_digit = false;
   double value = 0.0;
   double fractional_scale = 0.1;

   for(int index = 0; index < StringLen(normalized); index++)
   {
      ushort ch = StringGetCharacter(normalized, index);
      if(index == 0 && ch == '-')
      {
         negative = true;
         continue;
      }

      if(ch >= '0' && ch <= '9')
      {
         saw_digit = true;
         int digit = (int)(ch - '0');
         if(!seen_separator)
            value = (value * 10.0) + digit;
         else
         {
            value += digit * fractional_scale;
            fractional_scale *= 0.1;
         }
         continue;
      }

      if((ch == '.' || ch == ',') && !seen_separator)
      {
         seen_separator = true;
         continue;
      }

      if(ch == 0 || ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n')
         continue;

      return(0.0);
   }

   if(!saw_digit)
      return(0.0);
   if(negative)
      value *= -1.0;
   return(value);
}

void ExecuteTradeCommand(TradeCommand &command)
{
   command.comment = BuildTradeComment(command);
   PrintFormat(
      "TelegramSignalCopierEA executing request=%s symbol=%s action=%s order_type=%s volume=%.2f",
      command.request_id,
      command.symbol,
      command.action,
      command.order_type,
      command.volume
   );

   if(IsCommandStale(command))
   {
      WriteResult(command.request_id, "REJECTED", "Bridge command expired before EA consumed it", 0, 0.0);
      return;
   }

   if(!IsSymbolAllowed(command.symbol))
   {
      WriteResult(command.request_id, "REJECTED", "Symbol not allowed by EA configuration: " + command.symbol, 0, 0.0);
      return;
   }
   if(!SymbolSelect(command.symbol, true))
   {
      WriteResult(command.request_id, "ERROR", "Failed to select symbol in terminal", 0, 0.0);
      return;
   }

   bool success = false;
   string error_message = "";
   ResetLastError();

   if(command.order_type == "MARKET")
      success = ExecuteMarketOrder(command, error_message);
   else
      success = ExecutePendingOrder(command, error_message);

   if(success)
   {
      ulong ticket = trade.ResultDeal();
      if(ticket == 0)
         ticket = trade.ResultOrder();
      WriteResult(
         command.request_id,
         "FILLED",
         trade.ResultRetcodeDescription(),
         ticket,
         trade.ResultPrice()
      );
      return;
   }

   string failure_message = error_message;
   if(failure_message == "")
      failure_message = trade.ResultRetcodeDescription();
   if(failure_message == "")
      failure_message = "Trade execution failed";

   WriteResult(command.request_id, "ERROR", failure_message, 0, 0.0);
}

bool ExecuteMarketOrder(TradeCommand &command, string &error_message)
{
   if(!AllowMarketOrders)
   {
      error_message = "Market orders disabled in EA settings";
      return(false);
   }

   double sl = NormalizePrice(command.symbol, command.stop_loss, command.has_stop_loss);
   double tp = NormalizePrice(command.symbol, command.take_profit, command.has_take_profit);

   if(command.action == "BUY")
      return(trade.Buy(command.volume, command.symbol, 0.0, sl, tp, command.comment));
   if(command.action == "SELL")
      return(trade.Sell(command.volume, command.symbol, 0.0, sl, tp, command.comment));

   error_message = "Unsupported market action";
   return(false);
}

bool ExecutePendingOrder(TradeCommand &command, string &error_message)
{
   if(!AllowPendingOrders)
   {
      error_message = "Pending orders disabled in EA settings";
      return(false);
   }
   if(!command.has_entry_price)
   {
      error_message = "Pending order missing entry price";
      return(false);
   }

   double price = NormalizePrice(command.symbol, command.entry_price, true);
   double sl = NormalizePrice(command.symbol, command.stop_loss, command.has_stop_loss);
   double tp = NormalizePrice(command.symbol, command.take_profit, command.has_take_profit);

   if(command.order_type == "BUY_LIMIT")
      return(trade.BuyLimit(command.volume, price, command.symbol, sl, tp, ORDER_TIME_GTC, 0, command.comment));
   if(command.order_type == "SELL_LIMIT")
      return(trade.SellLimit(command.volume, price, command.symbol, sl, tp, ORDER_TIME_GTC, 0, command.comment));
   if(command.order_type == "BUY_STOP")
      return(trade.BuyStop(command.volume, price, command.symbol, sl, tp, ORDER_TIME_GTC, 0, command.comment));
   if(command.order_type == "SELL_STOP")
      return(trade.SellStop(command.volume, price, command.symbol, sl, tp, ORDER_TIME_GTC, 0, command.comment));

   error_message = "Unsupported pending order type";
   return(false);
}

string BuildTradeComment(TradeCommand &command)
{
   string normalized = command.comment;
   StringTrimLeft(normalized);
   StringTrimRight(normalized);
   if(normalized != "")
      return(normalized);

   string source = command.source_group;
   string slug = "";
   int length = StringLen(source);
   for(int index = 0; index < length; index++)
   {
      ushort ch = StringGetCharacter(source, index);
      bool is_digit = (ch >= '0' && ch <= '9');
      bool is_upper = (ch >= 'A' && ch <= 'Z');
      bool is_lower = (ch >= 'a' && ch <= 'z');

      if(is_digit || is_upper || is_lower)
         slug += CharToString((uchar)ch);
      else if(slug == "" || StringSubstr(slug, StringLen(slug) - 1, 1) != "-")
         slug += "-";

      if(StringLen(slug) >= 16)
         break;
   }

   StringTrimLeft(slug);
   StringTrimRight(slug);
   while(StringLen(slug) > 0 && StringSubstr(slug, StringLen(slug) - 1, 1) == "-")
      slug = StringSubstr(slug, 0, StringLen(slug) - 1);
   if(slug == "")
      slug = "UNKNOWN";

   string message_suffix = command.message_id;
   if(StringLen(message_suffix) > 8)
      message_suffix = StringSubstr(message_suffix, StringLen(message_suffix) - 8);

   return("TG|" + slug + "|" + message_suffix);
}

double NormalizePrice(const string symbol, const double price, const bool has_value)
{
   if(!has_value)
      return(0.0);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   return(NormalizeDouble(price, digits));
}

bool IsCommandStale(const TradeCommand &command)
{
   if(MaxCommandAgeSeconds <= 0)
      return(false);
   if(!command.has_submitted_epoch || command.submitted_epoch <= 0)
      return(false);

   // Use TimeGMT() so the comparison is always UTC vs UTC.
   // TimeLocal() is offset by the machine timezone and would make every command
   // appear stale on machines running in UTC+N timezones.
   long age_seconds = (long)TimeGMT() - command.submitted_epoch;
   if(age_seconds < 0)
      age_seconds = 0;
   return(age_seconds > MaxCommandAgeSeconds);
}

bool SymbolMatchesAllowedItem(const string symbol, const string allowed_item)
{
   string normalized_symbol = TrimmedCopy(symbol);
   string normalized_allowed = TrimmedCopy(allowed_item);
   if(normalized_symbol == "" || normalized_allowed == "")
      return(false);
   if(normalized_symbol == normalized_allowed)
      return(true);

   int allowed_length = StringLen(normalized_allowed);
   int symbol_length = StringLen(normalized_symbol);
   int suffix_length = symbol_length - allowed_length;
   if(symbol_length > allowed_length && suffix_length <= 4 && StringSubstr(normalized_symbol, 0, allowed_length) == normalized_allowed)
      return(true);

   return(false);
}

bool IsSymbolAllowed(const string symbol)
{
   string allowed = AllowedSymbols;
   StringReplace(allowed, " ", "");
   if(allowed == "")
      return(true);

   string items[];
   int count = StringSplit(allowed, ',', items);
   for(int index = 0; index < count; index++)
   {
      if(SymbolMatchesAllowedItem(symbol, items[index]))
         return(true);
   }
   return(false);
}

string StripExtension(const string filename)
{
   int separator = StringFind(filename, ".");
   if(separator < 0)
      return(filename);
   return(StringSubstr(filename, 0, separator));
}

string CommandFilePrefix()
{
   string prefix = BridgeFolderName;
   StringReplace(prefix, "/", "_");
   StringReplace(prefix, "\\", "_");
   return(prefix + "__");
}

string RequestIdFromCommandFilename(const string filename)
{
   string stem = StripExtension(filename);
   string prefix = CommandFilePrefix();
   if(StringFind(stem, prefix) == 0)
      return(StringSubstr(stem, StringLen(prefix)));
   return(stem);
}

int ReadQueuedRequestIds(string &request_ids[])
{
   ArrayResize(request_ids, 0);

   string path = BridgeFolderName + "/command_queue.txt";
   int file_handle = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(file_handle == INVALID_HANDLE)
      return(0);

   while(!FileIsEnding(file_handle))
   {
      string request_id = FileReadString(file_handle);
      if(request_id == "")
         continue;

      bool already_added = false;
      for(int i = 0; i < ArraySize(request_ids); i++)
      {
         if(request_ids[i] == request_id)
         {
            already_added = true;
            break;
         }
      }
      if(already_added)
         continue;

      int index = ArraySize(request_ids);
      ArrayResize(request_ids, index + 1);
      request_ids[index] = request_id;
   }

   FileClose(file_handle);
   return(ArraySize(request_ids));
}

void RewriteCommandQueue(const string &request_ids[])
{
   string path = BridgeFolderName + "/command_queue.txt";
   if(ArraySize(request_ids) == 0)
   {
      FileDelete(path, FILE_COMMON);
      return;
   }

   int file_handle = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(file_handle == INVALID_HANDLE)
      return;

   for(int i = 0; i < ArraySize(request_ids); i++)
      FileWriteString(file_handle, request_ids[i] + "\n");

   FileClose(file_handle);
}

void WriteResult(
   const string request_id,
   const string status,
   const string message,
   const ulong ticket,
   const double executed_price
)
{
   g_last_bridge_request_id = request_id;
   g_last_bridge_status = status;
   g_last_bridge_message = message;
   string ticket_text = (ticket > 0 ? IntegerToString((int)ticket) : "0");
   PrintFormat(
      "TelegramSignalCopierEA result request=%s status=%s ticket=%s message=%s",
      request_id,
      status,
      ticket_text,
      message
   );

   string path = BridgeFolderName + "/outbox/" + request_id + ".result";
   int file_handle = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(file_handle == INVALID_HANDLE)
      return;

   FileWriteString(file_handle, "request_id=" + request_id + "\n");
   FileWriteString(file_handle, "status=" + status + "\n");
   FileWriteString(file_handle, "message=" + message + "\n");
   if(ticket > 0)
      FileWriteString(file_handle, "ticket=" + IntegerToString((int)ticket) + "\n");
   if(executed_price > 0.0)
      FileWriteString(file_handle, "executed_price=" + DoubleToString(executed_price, _Digits) + "\n");
   FileWriteString(file_handle, "executed_at=" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\n");
   FileClose(file_handle);
   WriteEAStatus();
}

void WriteEAStatus()
{
   string path = BridgeFolderName + "/ea_status.txt";
   int file_handle = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(file_handle == INVALID_HANDLE)
      return;

   // Write UTC epoch so Python (which uses time.time() = UTC) can compare correctly.
   // TimeLocal() is offset by machine timezone and would confuse Python-side monitors.
   FileWriteString(file_handle, "expert_name=" + MQLInfoString(MQL_PROGRAM_NAME) + "\n");
   FileWriteString(file_handle, "chart_symbol=" + _Symbol + "\n");
   FileWriteString(file_handle, "heartbeat_epoch=" + IntegerToString((int)TimeGMT()) + "\n");
   FileWriteString(file_handle, "heartbeat_display=" + TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS) + "\n");
   FileWriteString(file_handle, "allowed_symbols=" + AllowedSymbols + "\n");
   FileWriteString(file_handle, "terminal_data_path=" + TerminalInfoString(TERMINAL_DATA_PATH) + "\n");
   FileWriteString(file_handle, "last_request_id=" + g_last_bridge_request_id + "\n");
   FileWriteString(file_handle, "last_status=" + g_last_bridge_status + "\n");
   FileWriteString(file_handle, "last_message=" + g_last_bridge_message + "\n");
   FileClose(file_handle);
}