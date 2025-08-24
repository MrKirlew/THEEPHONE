import 'package:flutter/material.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:image_picker/image_picker.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter/services.dart';
import 'dart:io';
import 'dart:convert';
import 'dart:async';
import 'api_client.dart'; // Use the fixed API client
import 'auth_service.dart';

class UnifiedAIScreen extends StatefulWidget {
  const UnifiedAIScreen({Key? key}) : super(key: key);

  @override
  _UnifiedAIScreenState createState() => _UnifiedAIScreenState();
}

class _UnifiedAIScreenState extends State<UnifiedAIScreen> {
  final TextEditingController _messageController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final AuthService _authService = AuthService();
  final ApiClient _apiClient = ApiClient(); // This now uses localhost:8080
  final ImagePicker _imagePicker = ImagePicker();
  
  // Platform channel for SMS sending
  static const platform = MethodChannel('com.kirlewai.adk_mobile_app/sms');
  
  List<ChatMessage> _messages = [];
  bool _isLoading = false;
  bool _isSignedIn = false;
  bool _ollamaRunning = false; // Track Ollama status
  GoogleSignInAccount? _currentUser;
  File? _selectedImage;
  String? _accessToken;
  Timer? _ollamaCheckTimer;
  
  @override
  void initState() {
    super.initState();
    _initializeServices();
    _requestPermissions();
    _checkOllamaStatus(); // Check initial status
    
    // Set up periodic Ollama check every 30 seconds
    _ollamaCheckTimer = Timer.periodic(Duration(seconds: 30), (_) {
      _checkOllamaStatus();
    });
  }
  
  @override
  void dispose() {
    _ollamaCheckTimer?.cancel();
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }
  
  Future<void> _checkOllamaStatus() async {
    try {
      final response = await _apiClient.checkOllamaStatus();
      if (mounted) {
        setState(() {
          _ollamaRunning = response['ollama_available'] ?? false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _ollamaRunning = false;
        });
      }
    }
  }
  
  Future<void> _requestPermissions() async {
    // Request SMS permission
    final smsStatus = await Permission.sms.request();
    
    // Request camera permission
    final cameraStatus = await Permission.camera.request();
    if (!cameraStatus.isGranted) {
      _showSnackBar('Camera permission is required for image capture');
    }
    
    // Request storage permission for saving images
    final storageStatus = await Permission.storage.request();
  }
  
  Future<void> _initializeServices() async {
    try {
      _currentUser = await _authService.getCurrentUser();
      if (_currentUser != null) {
        final auth = await _currentUser!.authentication;
        _accessToken = auth.accessToken;
        setState(() {
          _isSignedIn = true;
        });
      }
    } catch (e) {
      print('Error initializing services: $e');
    }
  }
  
  Future<void> _handleSignIn() async {
    try {
      final account = await _authService.signIn();
      if (account != null) {
        final auth = await account.authentication;
        setState(() {
          _currentUser = account;
          _accessToken = auth.accessToken;
          _isSignedIn = true;
        });
        _showSnackBar('Signed in as ${account.displayName}');
      }
    } catch (e) {
      _showSnackBar('Sign in failed: $e');
    }
  }
  
  Future<void> _handleSignOut() async {
    await _authService.signOut();
    setState(() {
      _currentUser = null;
      _accessToken = null;
      _isSignedIn = false;
    });
    _showSnackBar('Signed out successfully');
  }
  
  Future<void> _pickImage(ImageSource source) async {
    try {
      final XFile? image = await _imagePicker.pickImage(
        source: source,
        maxWidth: 1920,
        maxHeight: 1080,
        imageQuality: 85,
      );
      
      if (image != null) {
        setState(() {
          _selectedImage = File(image.path);
        });
        _showSnackBar('Image selected. Add a message and send to process.');
      }
    } catch (e) {
      _showSnackBar('Error picking image: $e');
    }
  }
  
  Future<void> _sendMessage() async {
    final message = _messageController.text.trim();
    if (message.isEmpty && _selectedImage == null) return;
    
    setState(() {
      _isLoading = true;
      if (message.isNotEmpty) {
        _messages.add(ChatMessage(
          text: message,
          isUser: true,
          image: _selectedImage,
          timestamp: DateTime.now(),
        ));
      }
      _messageController.clear();
    });
    
    _scrollToBottom();
    
    try {
      Map<String, dynamic> result;
      
      // Check if image processing is needed
      if (_selectedImage != null) {
        result = await _handleImageRequest(message);
      } 
      // Regular text request
      else {
        result = await _apiClient.sendMessage(
          message: message,
          accessToken: _accessToken,
        );
      }
      
      // Handle different response types
      String response = result['response'] ?? 'No response received';
      
      // NEW: Check if this is an SMS command that needs execution
      if (result['instruction'] == 'SEND_SMS') {
        await _executeSms(result);
        // Update response to show SMS was processed
        response = result['response'] ?? 'SMS is ready to send';
      }
      
      setState(() {
        _messages.add(ChatMessage(
          text: response,
          isUser: false,
          timestamp: DateTime.now(),
        ));
        _selectedImage = null;
      });
      
      _scrollToBottom();
      
    } catch (e) {
      setState(() {
        _messages.add(ChatMessage(
          text: 'Error: ${e.toString()}',
          isUser: false,
          isError: true,
          timestamp: DateTime.now(),
        ));
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }
  
  // NEW: Execute SMS sending - ACTUALLY SEND SMS
  Future<void> _executeSms(Map<String, dynamic> smsData) async {
    try {
      final recipient = smsData['recipient'];
      final message = smsData['message_content'];
      final contactName = smsData['contact_name'] ?? recipient;
      
      if (recipient == null || message == null) {
        _showSnackBar('Invalid SMS data received');
        return;
      }
      
      // Check SMS permission
      final smsPermission = await Permission.sms.status;
      if (!smsPermission.isGranted) {
        final result = await Permission.sms.request();
        if (!result.isGranted) {
          _showSnackBar('SMS permission is required to send messages');
          return;
        }
      }
      
      // Send SMS directly using platform channel
      try {
        if (Platform.isAndroid) {
          // Use native Android SMS manager to send SMS directly
          await platform.invokeMethod('sendSMS', {
            'phoneNumber': recipient,
            'message': message,
          });
        } else {
          throw Exception('SMS sending only supported on Android');
        }
        _showSnackBar('✅ SMS sent to $contactName successfully!');
        
        // Add a system message to show SMS was sent
        setState(() {
          _messages.add(ChatMessage(
            text: '📱 SMS sent to $contactName: "$message"',
            isUser: false,
            timestamp: DateTime.now(),
          ));
        });
        _scrollToBottom();
        
      } catch (smsError) {
        // If direct SMS sending fails, show error - NO SMS APP OPENING
        _showSnackBar('❌ Failed to send SMS: ${smsError.toString()}');
        
        setState(() {
          _messages.add(ChatMessage(
            text: '❌ Failed to send SMS to $contactName: ${smsError.toString()}',
            isUser: false,
            isError: true,
            timestamp: DateTime.now(),
          ));
        });
        _scrollToBottom();
      }
      
    } catch (e) {
      _showSnackBar('Failed to send SMS: $e');
    }
  }
  
  Future<Map<String, dynamic>> _handleImageRequest(String message) async {
    if (_selectedImage == null) return {'response': 'No image selected'};
    
    try {
      final bytes = await _selectedImage!.readAsBytes();
      
      final result = await _apiClient.sendUnifiedQuery(
        message: message.isEmpty ? 'Process this image' : message,
        imageData: bytes,
        accessToken: _accessToken,
      );
      
      return result;
    } catch (e) {
      return {'response': 'Error processing image: ${e.toString()}'};
    }
  }
  
  void _scrollToBottom() {
    Future.delayed(Duration(milliseconds: 100), () {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }
  
  void _showSnackBar(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }
  
  void _clearSelectedImage() {
    setState(() {
      _selectedImage = null;
    });
  }
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Color(0xFFF5F5F5),
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.white,
        title: Row(
          children: [
            Container(
              padding: EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Theme.of(context).primaryColor.withOpacity(0.1),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                Icons.smart_toy,
                color: Theme.of(context).primaryColor,
                size: 24,
              ),
            ),
            SizedBox(width: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      'Kirlew AI Assistant',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        color: Colors.black87,
                      ),
                    ),
                    SizedBox(width: 8),
                    // FIXED: Ollama status indicator
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: _ollamaRunning ? Colors.green : Colors.orange,
                      ),
                    ),
                  ],
                ),
                if (_isSignedIn && _currentUser != null)
                  Text(
                    _currentUser!.email ?? '',
                    style: TextStyle(
                      fontSize: 12,
                      color: Colors.grey[600],
                    ),
                  ),
              ],
            ),
          ],
        ),
        actions: [
          if (!_isSignedIn)
            TextButton.icon(
              onPressed: _handleSignIn,
              icon: Icon(Icons.login),
              label: Text('Sign In'),
              style: TextButton.styleFrom(
                foregroundColor: Theme.of(context).primaryColor,
              ),
            )
          else
            PopupMenuButton<String>(
              icon: CircleAvatar(
                backgroundImage: _currentUser?.photoUrl != null
                    ? NetworkImage(_currentUser!.photoUrl!)
                    : null,
                child: _currentUser?.photoUrl == null
                    ? Icon(Icons.person, size: 20)
                    : null,
              ),
              onSelected: (value) {
                if (value == 'signout') {
                  _handleSignOut();
                }
              },
              itemBuilder: (context) => [
                PopupMenuItem(
                  value: 'profile',
                  child: ListTile(
                    leading: Icon(Icons.person),
                    title: Text(_currentUser?.displayName ?? 'User'),
                    subtitle: Text(_currentUser?.email ?? ''),
                  ),
                ),
                PopupMenuDivider(),
                PopupMenuItem(
                  value: 'signout',
                  child: ListTile(
                    leading: Icon(Icons.logout),
                    title: Text('Sign Out'),
                  ),
                ),
              ],
            ),
        ],
      ),
      body: Column(
        children: [
          // Service indicators
          if (_isSignedIn)
            Container(
              padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              color: Colors.white,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    _buildServiceChip(Icons.calendar_today, 'Calendar', true),
                    _buildServiceChip(Icons.email, 'Gmail', true),
                    _buildServiceChip(Icons.folder, 'Drive', true),
                    _buildServiceChip(Icons.contacts, 'Contacts', true),
                    _buildServiceChip(Icons.message, 'SMS', true),
                    _buildServiceChip(Icons.table_chart, 'Sheets', true),
                    _buildServiceChip(Icons.description, 'Docs', true),
                    _buildServiceChip(Icons.task, 'Tasks', true),
                    _buildServiceChip(Icons.note, 'Keep', true),
                    _buildServiceChip(Icons.slideshow, 'Slides', true),
                    _buildServiceChip(Icons.quiz, 'Forms', true),
                  ],
                ),
              ),
            ),
          
          // Chat messages
          Expanded(
            child: _messages.isEmpty
                ? _buildWelcomeView()
                : ListView.builder(
                    controller: _scrollController,
                    padding: EdgeInsets.all(16),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      return _buildMessageBubble(_messages[index]);
                    },
                  ),
          ),
          
          // Selected image preview
          if (_selectedImage != null)
            Container(
              padding: EdgeInsets.all(8),
              color: Colors.white,
              child: Row(
                children: [
                  Container(
                    width: 60,
                    height: 60,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(8),
                      image: DecorationImage(
                        image: FileImage(_selectedImage!),
                        fit: BoxFit.cover,
                      ),
                    ),
                  ),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Image ready to process',
                      style: TextStyle(fontSize: 14),
                    ),
                  ),
                  IconButton(
                    icon: Icon(Icons.close),
                    onPressed: _clearSelectedImage,
                  ),
                ],
              ),
            ),
          
          // Input area
          Container(
            decoration: BoxDecoration(
              color: Colors.white,
              boxShadow: [
                BoxShadow(
                  offset: Offset(0, -2),
                  blurRadius: 4,
                  color: Colors.black.withOpacity(0.05),
                ),
              ],
            ),
            child: Padding(
              padding: EdgeInsets.all(12),
              child: Row(
                children: [
                  // Camera button
                  IconButton(
                    icon: Icon(Icons.camera_alt),
                    onPressed: () => _pickImage(ImageSource.camera),
                    color: Theme.of(context).primaryColor,
                  ),
                  
                  // Gallery button
                  IconButton(
                    icon: Icon(Icons.photo),
                    onPressed: () => _pickImage(ImageSource.gallery),
                    color: Theme.of(context).primaryColor,
                  ),
                  
                  // Text input
                  Expanded(
                    child: Container(
                      decoration: BoxDecoration(
                        color: Colors.grey[100],
                        borderRadius: BorderRadius.circular(24),
                      ),
                      child: TextField(
                        controller: _messageController,
                        maxLines: null,
                        textInputAction: TextInputAction.send,
                        onSubmitted: (_) => _sendMessage(),
                        decoration: InputDecoration(
                          hintText: _selectedImage != null 
                              ? 'Describe what to do with the image...' 
                              : 'Ask me anything...',
                          border: InputBorder.none,
                          contentPadding: EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 10,
                          ),
                        ),
                      ),
                    ),
                  ),
                  
                  SizedBox(width: 8),
                  
                  // Send button
                  Container(
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: Theme.of(context).primaryColor,
                    ),
                    child: IconButton(
                      icon: _isLoading
                          ? SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                valueColor: AlwaysStoppedAnimation<Color>(
                                  Colors.white,
                                ),
                              ),
                            )
                          : Icon(Icons.send, color: Colors.white),
                      onPressed: _isLoading ? null : _sendMessage,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
  
  Widget _buildServiceChip(IconData icon, String label, bool active) {
    return Container(
      margin: EdgeInsets.only(right: 8),
      child: Chip(
        avatar: Icon(icon, size: 16, color: active ? Colors.white : Colors.grey),
        label: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            color: active ? Colors.white : Colors.grey,
          ),
        ),
        backgroundColor: active 
            ? Theme.of(context).primaryColor 
            : Colors.grey[200],
      ),
    );
  }
  
  Widget _buildWelcomeView() {
    return Center(
      child: SingleChildScrollView(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.smart_toy,
              size: 64,
              color: Theme.of(context).primaryColor.withOpacity(0.5),
            ),
            SizedBox(height: 16),
            Text(
              'Welcome to Kirlew AI',
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.bold,
              ),
            ),
            SizedBox(height: 8),
            Text(
              'Your intelligent assistant for all Google services',
              style: TextStyle(
                fontSize: 16,
                color: Colors.grey[600],
              ),
              textAlign: TextAlign.center,
            ),
            // Show Ollama status in welcome screen
            if (!_ollamaRunning)
              Container(
                margin: EdgeInsets.only(top: 16),
                padding: EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.orange.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.orange.withOpacity(0.3)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.warning, color: Colors.orange, size: 20),
                    SizedBox(width: 8),
                    Text(
                      'Ollama AI not running',
                      style: TextStyle(color: Colors.orange[700]),
                    ),
                  ],
                ),
              ),
            SizedBox(height: 32),
            if (!_isSignedIn) ...[
              ElevatedButton.icon(
                onPressed: _handleSignIn,
                icon: Icon(Icons.login),
                label: Text('Sign in with Google'),
                style: ElevatedButton.styleFrom(
                  padding: EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                ),
              ),
              SizedBox(height: 16),
            ],
            _buildSuggestionCard(
              'Try saying:',
              [
                '"What\'s on my calendar today?"',
                '"Text John saying I\'ll be late"',
                '"Create a new document about project ideas"',
                '"What was the last email sent to me?"',
                '"Create a spreadsheet for expenses"',
                '"Create a form for feedback"',
              ],
            ),
          ],
        ),
      ),
    );
  }
  
  Widget _buildSuggestionCard(String title, List<String> suggestions) {
    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
      ),
      child: Padding(
        padding: EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
              ),
            ),
            SizedBox(height: 12),
            ...suggestions.map((s) => Padding(
              padding: EdgeInsets.symmetric(vertical: 4),
              child: Row(
                children: [
                  Icon(Icons.arrow_right, size: 16, color: Colors.grey),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      s,
                      style: TextStyle(
                        fontSize: 14,
                        color: Colors.grey[700],
                      ),
                    ),
                  ),
                ],
              ),
            )).toList(),
          ],
        ),
      ),
    );
  }
  
  Widget _buildMessageBubble(ChatMessage message) {
    final isUser = message.isUser;
    
    return Padding(
      padding: EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (!isUser) ...[
            CircleAvatar(
              radius: 16,
              backgroundColor: Theme.of(context).primaryColor,
              child: Icon(Icons.smart_toy, size: 20, color: Colors.white),
            ),
            SizedBox(width: 8),
          ],
          Flexible(
            child: Container(
              constraints: BoxConstraints(
                maxWidth: MediaQuery.of(context).size.width * 0.75,
              ),
              decoration: BoxDecoration(
                color: isUser 
                    ? Theme.of(context).primaryColor 
                    : message.isError 
                        ? Colors.red[50] 
                        : Colors.white,
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(16),
                  topRight: Radius.circular(16),
                  bottomLeft: isUser ? Radius.circular(16) : Radius.circular(4),
                  bottomRight: isUser ? Radius.circular(4) : Radius.circular(16),
                ),
                boxShadow: [
                  BoxShadow(
                    offset: Offset(0, 1),
                    blurRadius: 2,
                    color: Colors.black.withOpacity(0.1),
                  ),
                ],
              ),
              padding: EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (message.image != null)
                    Container(
                      margin: EdgeInsets.only(bottom: 8),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Image.file(
                          message.image!,
                          width: 200,
                          fit: BoxFit.cover,
                        ),
                      ),
                    ),
                  Text(
                    message.text,
                    style: TextStyle(
                      color: isUser 
                          ? Colors.white 
                          : message.isError 
                              ? Colors.red[700] 
                              : Colors.black87,
                      fontSize: 15,
                    ),
                  ),
                  SizedBox(height: 4),
                  Text(
                    _formatTime(message.timestamp),
                    style: TextStyle(
                      fontSize: 11,
                      color: isUser 
                          ? Colors.white70 
                          : Colors.grey[500],
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (isUser) ...[
            SizedBox(width: 8),
            CircleAvatar(
              radius: 16,
              backgroundImage: _currentUser?.photoUrl != null
                  ? NetworkImage(_currentUser!.photoUrl!)
                  : null,
              child: _currentUser?.photoUrl == null
                  ? Icon(Icons.person, size: 20)
                  : null,
            ),
          ],
        ],
      ),
    );
  }
  
  String _formatTime(DateTime time) {
    final hour = time.hour > 12 ? time.hour - 12 : time.hour;
    final period = time.hour >= 12 ? 'PM' : 'AM';
    return '${hour == 0 ? 12 : hour}:${time.minute.toString().padLeft(2, '0')} $period';
  }
}

class ChatMessage {
  final String text;
  final bool isUser;
  final bool isError;
  final File? image;
  final DateTime timestamp;
  
  ChatMessage({
    required this.text,
    required this.isUser,
    this.isError = false,
    this.image,
    required this.timestamp,
  });
}